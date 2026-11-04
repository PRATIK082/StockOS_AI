"""FastAPI dependencies: current-user auth and RBAC guards."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token, is_token_revoked, role_at_least
from app.db.models import User
from app.db.session import get_session


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_token(creds.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    jti = payload.get("jti")
    if jti and is_token_revoked(jti):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")
    from sqlalchemy import select

    user = await session.scalar(select(User).where(User.id == payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or disabled")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User | None:
    """Like get_current_user but returns None when no/invalid token.

    Lets public routes (e.g. /chat) offer per-user extras to signed-in
    callers without breaking anonymous access.
    """
    if creds is None:
        return None
    try:
        payload = decode_token(creds.credentials)
    except Exception:  # noqa: BLE001 - treat as anonymous
        return None
    if payload is None:
        return None
    jti = payload.get("jti")
    if jti and is_token_revoked(jti):
        return None
    from sqlalchemy import select

    user = await session.scalar(select(User).where(User.id == payload.get("sub")))
    if user is None or not user.is_active:
        return None
    return user


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_role(min_role: str):
    async def guard(user: CurrentUser) -> User:
        if not role_at_least(min_role, user.role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return guard