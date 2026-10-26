"""Authentication routes: register, login, me, and TOTP 2FA."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    TOTPSetupResponse,
    TOTPVerifyRequest,
)
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    generate_totp_secret,
    hash_password,
    needs_rehash,
    totp_provisioning_uri,
    verify_password,
    verify_totp,
)
from app.db.models import User
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(f"{settings.rate_limit_auth_per_minute}/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    existing = await session.scalar(
        select(User).where(or_(User.email == body.email, User.username == body.username))
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already registered")

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return _token_for(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(f"{settings.rate_limit_auth_per_minute}/minute")
async def login(
    request: Request,
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    user = await session.scalar(
        select(User).where(or_(User.email == body.identifier, User.username == body.identifier))
    )
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    # Upgrade legacy password hashes transparently.
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(body.password)
        await session.commit()

    # TOTP second factor.
    if user.totp_enabled:
        if not body.totp_code or not verify_totp(user.totp_secret or "", body.totp_code):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing 2FA code")

    return _token_for(user)


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "totp_enabled": user.totp_enabled,
    }


@router.post("/totp/setup", response_model=TOTPSetupResponse)
async def totp_setup(user: CurrentUser, session: AsyncSession = Depends(get_session)) -> TOTPSetupResponse:
    if not user.totp_secret:
        user.totp_secret = generate_totp_secret()
        await session.commit()
        await session.refresh(user)
    secret = user.totp_secret or ""
    return TOTPSetupResponse(
        secret=secret,
        provisioning_uri=totp_provisioning_uri(secret, user.username),
        enabled=user.totp_enabled,
    )


@router.post("/totp/verify")
async def totp_verify(
    body: TOTPVerifyRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "TOTP not set up")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid 2FA code")
    user.totp_enabled = True
    await session.commit()
    return {"enabled": True}


@router.post("/totp/disable")
async def totp_disable(
    body: TOTPVerifyRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not user.totp_enabled:
        return {"enabled": False}
    if not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid 2FA code")
    user.totp_enabled = False
    user.totp_secret = None
    await session.commit()
    return {"enabled": False}


def _token_for(user: User) -> TokenResponse:
    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token,
        user={"id": user.id, "email": user.email, "username": user.username, "role": user.role},
    )

