"""Firebase Authentication dependency.

Every dashboard endpoint depends on `get_current_uid`, which reads the
`Authorization: Bearer <idToken>` header, verifies it with the Firebase Admin
SDK, and returns the authenticated user's uid. All dashboard data is then
scoped to that uid so each user only ever sees their own repositories and runs.
"""

from fastapi import Header, HTTPException
from firebase_admin import auth as firebase_auth


async def get_current_uid(authorization: str = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authentication token")

    token = authorization.split(" ", 1)[1].strip()
    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")

    uid = decoded.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication token has no user id")
    return uid