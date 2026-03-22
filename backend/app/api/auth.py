"""
Authentication endpoints:
- POST /api/auth/register   — email + password
- POST /api/auth/login      — email + password
- GET  /api/auth/google     — redirect to Google OAuth
- GET  /api/auth/google/callback
- GET  /api/auth/me         — current user info
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", truncate_error=False)
settings = get_settings()


# ─────────────────── Schemas ───────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str


# ─────────────────── JWT helpers ───────────────────

def create_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get("access_token") or (
        request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


# ─────────────────── Routes ───────────────────

@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=pwd_ctx.hash(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    from fastapi.responses import JSONResponse
    response = JSONResponse({"access_token": create_token(user.id), "token_type": "bearer"})
    response.set_cookie("access_token", create_token(user.id), httponly=True, samesite="lax")
    return response


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not pwd_ctx.verify(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    from fastapi.responses import JSONResponse
    token = create_token(user.id)
    response = JSONResponse({"access_token": token, "token_type": "bearer"})
    response.set_cookie("access_token", token, httponly=True, samesite="lax")
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email}


@router.post("/logout")
async def logout():
    from fastapi.responses import JSONResponse
    response = JSONResponse({"message": "logged out"})
    response.delete_cookie("access_token")
    return response


# ─────────────────── Google OAuth ───────────────────

@router.get("/google")
async def google_login():
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.frontend_url}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    from urllib.parse import urlencode
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(code: str, db: AsyncSession = Depends(get_db)):
    import httpx

    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.frontend_url}/api/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        token_data = token_resp.json()
        id_token = token_data.get("id_token", "")

        # Decode id_token without verification (for simplicity; add jwks validation for production)
        import base64, json as _json
        payload_b64 = id_token.split(".")[1] + "=="
        payload = _json.loads(base64.urlsafe_b64decode(payload_b64))

    email = payload.get("email", "")
    google_id = payload.get("sub", "")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        user = User(email=email, google_id=google_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    token = create_token(user.id)
    response = RedirectResponse(url="/dashboard")
    response.set_cookie("access_token", token, httponly=True, samesite="lax")
    return response
