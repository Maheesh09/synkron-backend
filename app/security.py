"""Shared security helpers for the internal endpoints."""

import hmac
from fastapi import Header, HTTPException
from app.config import settings


def require_internal_token(x_internal_token: str = Header(None)) -> None:
    """
    Guard the /internal/* endpoints. They run the pipeline with a caller-
    supplied payload and are reachable publicly (the Cloud Run service allows
    unauthenticated ingress), so this shared secret is the only thing between
    the internet and the pipeline. Compare it in constant time so an attacker
    can't recover it byte by byte from response timing, and refuse an empty
    configured secret so a blank INTERNAL_SECRET never authorises anyone.
    """
    expected = settings.INTERNAL_SECRET
    if not x_internal_token or not expected or not hmac.compare_digest(
        x_internal_token.encode(), expected.encode()
    ):
        raise HTTPException(status_code=403, detail="Forbidden")