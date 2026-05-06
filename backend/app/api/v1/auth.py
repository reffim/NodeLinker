"""Auth endpoints: local accounts + OIDC Authorization Code flow."""
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.models import User
from app.schemas.auth import (
    LoginRequest,
    OIDCLoginResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Used to sign OIDC state+nonce so we can verify them on callback
_signer = URLSafeTimedSerializer(settings.JWT_SECRET_KEY)


def _set_auth_cookies(response: Response, user: User) -> None:
    access = create_access_token(str(user.id), user.role)
    refresh = create_refresh_token(str(user.id))

    cookie_opts = dict(httponly=True, samesite="lax", secure=not settings.DEBUG)

    response.set_cookie(
        settings.ACCESS_TOKEN_COOKIE,
        access,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_opts,
    )
    response.set_cookie(
        settings.REFRESH_TOKEN_COOKIE,
        refresh,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **cookie_opts,
    )


# ---------------------------------------------------------------------------
# Local auth
# ---------------------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    # Check uniqueness
    existing = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username or email already registered")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role="admin" if await _is_first_user(db) else "operator",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    _set_auth_cookies(response, user)
    return TokenResponse(user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _set_auth_cookies(response, user)
    return TokenResponse(user=UserResponse.model_validate(user))


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(settings.ACCESS_TOKEN_COOKIE)
    response.delete_cookie(settings.REFRESH_TOKEN_COOKIE)
    return {"detail": "Logged out"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie(alias=settings.REFRESH_TOKEN_COOKIE)] = None,
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    _set_auth_cookies(response, user)
    return TokenResponse(user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.model_validate(current_user)


# ---------------------------------------------------------------------------
# OIDC
# ---------------------------------------------------------------------------

@router.get("/oidc/login", response_model=OIDCLoginResponse)
async def oidc_login() -> OIDCLoginResponse:
    if not settings.OIDC_ENABLED:
        raise HTTPException(status_code=404, detail="OIDC not configured")

    from app.core.oidc import get_authorization_url

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    # Sign state+nonce so callback can verify and recover nonce
    signed = _signer.dumps({"state": state, "nonce": nonce})

    auth_url = await get_authorization_url(state=signed, nonce=nonce)
    return OIDCLoginResponse(authorization_url=auth_url)


@router.get("/oidc/callback")
async def oidc_callback(
    code: str,
    state: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    if not settings.OIDC_ENABLED:
        raise HTTPException(status_code=404, detail="OIDC not configured")

    from app.core.oidc import exchange_code

    # Verify signed state (max age 10 min)
    try:
        data = _signer.loads(state, max_age=600)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired OIDC state")

    claims = await exchange_code(code=code, state=data["state"])

    # Find or create local user
    result = await db.execute(
        select(User).where(
            (User.oidc_sub == claims["sub"]) & (User.oidc_provider == claims["provider"])
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        # Possibly link by email
        if claims.get("email"):
            email_result = await db.execute(select(User).where(User.email == claims["email"]))
            user = email_result.scalar_one_or_none()

        if user is None:
            # Create new user
            username_base = (claims.get("email") or claims["sub"]).split("@")[0]
            username = await _unique_username(db, username_base)
            user = User(
                username=username,
                email=claims.get("email", f"{claims['sub']}@{claims['provider']}"),
                oidc_sub=claims["sub"],
                oidc_provider=claims["provider"],
                role="admin" if await _is_first_user(db) else "operator",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        else:
            user.oidc_sub = claims["sub"]
            user.oidc_provider = claims["provider"]
            await db.commit()

    redirect = RedirectResponse(url="/", status_code=302)
    _set_auth_cookies(redirect, user)
    return redirect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _is_first_user(db: AsyncSession) -> bool:
    from sqlalchemy import func, select
    result = await db.execute(select(func.count()).select_from(User))
    return result.scalar() == 0


async def _unique_username(db: AsyncSession, base: str) -> str:
    base = base[:50].replace(" ", "_")
    candidate = base
    for i in range(1, 100):
        result = await db.execute(select(User).where(User.username == candidate))
        if result.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base}_{i}"
    return f"{base}_{uuid.uuid4().hex[:8]}"
