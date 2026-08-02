"""
GitHub App authentication.

Implements the two-token flow every GitHub App uses:

  1. Sign a short-lived JWT with the App's PRIVATE key. This proves "I am the
     Synkron App." It is minted locally — no network call — and can only be
     used against App-level endpoints.
  2. Exchange that JWT for an *installation access token*, scoped to one
     installation's repositories and valid for ~1 hour.
  3. Cache installation tokens and reuse them until they near expiry, so we
     mint at most one per installation per hour instead of on every request.

All repository work — reading diffs and files, creating branches, committing,
opening pull requests — authenticates with the installation token, never the
JWT and never a personal access token.
"""

import base64
import time
import asyncio
import logging
from datetime import datetime

import jwt          # PyJWT
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
API_VERSION = "2026-03-10"
_ACCEPT = "application/vnd.github+json"

# Refresh an installation token when it has fewer than this many seconds left,
# so we never hand out a token that could expire mid-request.
_REFRESH_MARGIN_SECONDS = 300  # 5 minutes


def _load_private_key() -> str:
    """
    Return the App's private key as PEM text.

    Accepts either the raw PEM (recognised by the 'BEGIN' marker) or a
    base64-encoded PEM. The base64 form exists so the key can live on a single
    line in an env var or secret store — a multi-line PEM doesn't fit cleanly.
    """
    raw = settings.GITHUB_APP_PRIVATE_KEY.strip()
    if not raw:
        raise RuntimeError("GITHUB_APP_PRIVATE_KEY is not set")
    if "-----BEGIN" in raw:
        return raw
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception as e:
        raise RuntimeError(
            "GITHUB_APP_PRIVATE_KEY is neither a PEM nor valid base64-encoded PEM"
        ) from e


def _generate_jwt() -> str:
    """
    Create a signed JWT that authenticates Synkron *as the App itself*.

    Signed with RS256 using the App's private key; GitHub verifies it with the
    matching public key it already holds. Because verification uses the public
    key, no shared secret ever crosses the wire — only the holder of the
    private key could have produced a valid token.

    Claims:
      iat  issued-at, backdated 60s to tolerate minor clock skew between us
           and GitHub (a token "from the future" is rejected).
      exp  expiry. GitHub allows at most 10 minutes; we use 9 for headroom.
      iss  the App's identifier (App ID; GitHub also accepts the Client ID).
    """
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (9 * 60),
        "iss": settings.GITHUB_APP_ID,
    }
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")


# In-memory cache: installation_id -> {"token": str, "expires_at": epoch_seconds}
_token_cache: dict[int, dict] = {}
_cache_lock = asyncio.Lock()


async def get_installation_token(installation_id: int) -> str:
    """
    Return a valid installation access token for the given installation,
    minting a fresh one only when the cache is empty or the cached token is
    close to expiring. This is what the rest of the app calls before doing any
    GitHub work.

    The lock serialises the check-then-mint so two concurrent pipeline runs on
    the same installation can't both fire a mint request for the same token. At
    Synkron's scale one shared lock is fine; if token minting ever became a
    hot path you'd shard it into a lock per installation.
    """
    async with _cache_lock:
        cached = _token_cache.get(installation_id)
        if cached and cached["expires_at"] - time.time() > _REFRESH_MARGIN_SECONDS:
            return cached["token"]

        token, expires_at = await _mint_installation_token(installation_id)
        _token_cache[installation_id] = {"token": token, "expires_at": expires_at}
        return token


async def _mint_installation_token(installation_id: int) -> tuple[str, float]:
    """
    Exchange an App JWT for a fresh installation access token.

    POST /app/installations/{installation_id}/access_tokens
    Authenticated with the JWT as Bearer. Returns (token, expiry_epoch_seconds).
    """
    app_jwt = _generate_jwt()
    url = f"{API_BASE}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": _ACCEPT,
        "X-GitHub-Api-Version": API_VERSION,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    token = data["token"]
    # expires_at is ISO 8601 (e.g. "2026-08-02T12:34:56Z"). Convert the
    # trailing 'Z' to an explicit UTC offset so fromisoformat can parse it.
    expires_at = datetime.fromisoformat(
        data["expires_at"].replace("Z", "+00:00")
    ).timestamp()
    logger.info(f"Minted installation token for installation {installation_id}")
    return token, expires_at


async def app_request(method: str, path: str, **kwargs) -> httpx.Response:
    """
    Make an App-level API call authenticated with the JWT (not an installation
    token). Use this for endpoints that identify installations rather than act
    on repo contents, e.g.:

      GET /app/installations                 — list every install of this App
      GET /repos/{owner}/{repo}/installation — find the install for one repo

    The dashboard's onboarding flow (Phase 4) uses these to map a connected
    repo to its installation_id.
    """
    app_jwt = _generate_jwt()
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": _ACCEPT,
        "X-GitHub-Api-Version": API_VERSION,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
        resp.raise_for_status()
        return resp
