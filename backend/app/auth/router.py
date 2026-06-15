"""Auth router — register and login endpoints."""

import uuid
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.service import (
    hash_password,
    verify_password,
    create_access_token,
)
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User
from app.models.device import Device

router = APIRouter(tags=["auth"])


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from an org name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user.

    Creates an organization, user (all Owner role in Phase 1A),
    and a virtual_phone_mic device.
    """
    # Check if email already exists
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create organization
    slug = _slugify(body.org_name)
    # Ensure unique slug by appending a short suffix if needed
    existing_org = await db.execute(
        select(Organization).where(Organization.slug == slug)
    )
    if existing_org.scalar_one_or_none() is not None:
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    org = Organization(name=body.org_name, slug=slug)
    db.add(org)
    await db.flush()

    # Create user
    user = User(
        org_id=org.id,
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role="owner",
    )
    db.add(user)
    await db.flush()

    # Create virtual_phone_mic device
    device_key = f"virtual-{user.id}"
    device = Device(
        user_id=user.id,
        name="virtual_phone_mic",
        device_key=device_key,
        device_type="virtual_phone_mic",
        status="active",
    )
    db.add(device)
    await db.flush()

    # Generate token
    token = create_access_token(
        user_id=user.id,
        org_id=org.id,
        role=user.role,
    )

    return TokenResponse(
        access_token=token,
        user_id=str(user.id),
        org_id=str(org.id),
        role=user.role,
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user and return a JWT access token."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(
        user_id=user.id,
        org_id=user.org_id,
        role=user.role,
    )

    return TokenResponse(
        access_token=token,
        user_id=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
    )
