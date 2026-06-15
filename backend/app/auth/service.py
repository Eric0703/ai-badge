"""Auth service — password hashing, JWT creation and verification."""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(
    user_id: uuid.UUID, org_id: uuid.UUID, role: str
) -> str:
    """Create a JWT access token (1h expiry).

    Payload: sub (user_id), org_id, role.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Returns the payload dict on success.
    Raises JWTError if token is invalid or expired.
    """
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
