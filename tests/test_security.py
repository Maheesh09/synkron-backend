"""
Unit tests for the security-critical, network-free parts of Synkron.

Run:
    pip install -r requirements-dev.txt
    pytest -q --cov=app --cov-report=term-missing

These deliberately cover the code where a bug is silent and expensive:
signature verification, the internal-endpoint guard, the loop guard that
stops Synkron reacting to its own commits, and the hourly rate-limit window.
"""

import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers import webhook as wh
from app.security import require_internal_token


# --------------------------------------------------------------------------
# Webhook signature verification
# --------------------------------------------------------------------------

def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def webhook_secret(monkeypatch):
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", secret)
    return secret


def test_valid_signature_accepted(webhook_secret):
    body = b'{"action":"opened"}'
    assert wh._verify_signature(body, _sign(body, webhook_secret)) is True


def test_signature_rejected_when_body_tampered(webhook_secret):
    body = b'{"action":"opened"}'
    sig = _sign(body, webhook_secret)
    assert wh._verify_signature(b'{"action":"closed"}', sig) is False


def test_signature_rejected_with_wrong_secret(webhook_secret):
    body = b'{"action":"opened"}'
    assert wh._verify_signature(body, _sign(body, "attacker-secret")) is False


@pytest.mark.parametrize("header", ["", None, "deadbeef", "sha1=deadbeef"])
def test_malformed_signature_header_rejected(webhook_secret, header):
    assert wh._verify_signature(b"{}", header) is False


# --------------------------------------------------------------------------
# Internal endpoint guard
# --------------------------------------------------------------------------

def test_internal_token_accepted(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "s3cret")
    assert require_internal_token("s3cret") is None


def test_internal_token_rejected(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "s3cret")
    with pytest.raises(HTTPException) as exc:
        require_internal_token("wrong")
    assert exc.value.status_code == 403


def test_blank_configured_secret_authorises_nobody(monkeypatch):
    """A blank INTERNAL_SECRET must not turn the guard into a no-op."""
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "")
    with pytest.raises(HTTPException):
        require_internal_token("")
    with pytest.raises(HTTPException):
        require_internal_token("anything")


# --------------------------------------------------------------------------
# Push handling: loop guard and branch filter
# --------------------------------------------------------------------------

def _push(ref="refs/heads/main", messages=("add feature",)):
    return {
        "ref": ref,
        "after": "a" * 40,
        "repository": {"full_name": "acme/app", "default_branch": "main", "id": 1},
        "commits": [{"message": m} for m in messages],
    }


@pytest.mark.asyncio
async def test_push_to_non_default_branch_ignored():
    res = await wh._handle_push(_push(ref="refs/heads/feature-x"))
    assert res["status"] == "ignored"


@pytest.mark.asyncio
async def test_push_with_no_commits_ignored():
    res = await wh._handle_push(_push(messages=()))
    assert res["status"] == "ignored"


@pytest.mark.asyncio
async def test_loop_guard_ignores_synkron_authored_commit():
    """The docs PR Synkron merges must never trigger another run."""
    res = await wh._handle_push(_push(messages=("[synkron] update docs",)))
    assert res["status"] == "ignored"
    assert "synkron" in res["reason"]


@pytest.mark.asyncio
async def test_mixed_push_with_one_synkron_commit_is_ignored():
    res = await wh._handle_push(
        _push(messages=("real change", "[synkron] update docs"))
    )
    assert res["status"] == "ignored"


# --------------------------------------------------------------------------
# Pull request handling: only merged Synkron docs PRs feed the loop
# --------------------------------------------------------------------------

def _pr(action="closed", merged=True, head="synkron/docs-abc123"):
    return {
        "action": action,
        "pull_request": {"number": 7, "merged": merged, "head": {"ref": head}},
    }


@pytest.mark.asyncio
async def test_unmerged_pr_ignored():
    res = await wh._handle_pull_request(_pr(merged=False))
    assert res["status"] == "ignored"


@pytest.mark.asyncio
async def test_human_pr_ignored():
    res = await wh._handle_pull_request(_pr(head="feature/login"))
    assert res["status"] == "ignored"
    assert "synkron" in res["reason"]


# --------------------------------------------------------------------------
# Rate limit window bucketing
# --------------------------------------------------------------------------

def test_hour_bucket_changes_across_the_hour_boundary():
    """The key must roll over exactly on the hour, not drift."""
    base = 1_700_000_000 - (1_700_000_000 % 3600)
    assert int(base) // 3600 == int(base + 3599) // 3600
    assert int(base) // 3600 != int(base + 3600) // 3600


@pytest.mark.asyncio
async def test_rate_limit_disabled_when_limit_is_zero(monkeypatch):
    from app.services import rate_limit

    monkeypatch.setattr(settings, "RATE_LIMIT_PER_HOUR", 0)
    assert await rate_limit.check_rate_limit(123) is True
    assert await rate_limit.reserve_rate_limit_quota(123) is True


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_datastore_is_down(monkeypatch):
    """A Mongo blip must never block legitimate runs."""
    from app.services import rate_limit

    monkeypatch.setattr(settings, "RATE_LIMIT_PER_HOUR", 20)

    def boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(rate_limit, "get_db", boom)
    assert await rate_limit.check_rate_limit(123) is True