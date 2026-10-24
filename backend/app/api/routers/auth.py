"""Authentication routes: register, login, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
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
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    user = await session.scalar(
        select(User).where(or_(User.email == body.identifier, User.username == body.identifier))
    )
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    return _token_for(user)


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return {"id": user.id, "email": user.email, "username": user.username, "role": user.role}


def _token_for(user: User) -> TokenResponse:
    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token,
        user={"id": user.id, "email": user.email, "username": user.username, "role": user.role},
    )
