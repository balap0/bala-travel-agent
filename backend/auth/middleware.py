# Simple password authentication — no user accounts, just a shared password
# Issues JWT tokens for session management

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from jose import JWTError, jwt

from config import get_settings
from models.schemas import LoginRequest, LoginResponse

auth_router = APIRouter()

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7  # 1 week


def create_token(settings) -> str:
    """Create a JWT token valid for TOKEN_EXPIRE_HOURS."""
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"exp": expire, "sub": "user", "iat": datetime.utcnow()}
    return jwt.encode(payload, settings.session_secret, algorithm=ALGORITHM)


def verify_token(token: str, settings) -> bool:
    """Verify a JWT token is valid and not expired."""
    try:
        jwt.decode(token, settings.session_secret, algorithms=[ALGORITHM])
        return True
    except JWTError:
        return False


async def require_auth(authorization: Optional[str] = Header(None)) -> str:
    """Dependency that enforces authentication on endpoints."""
    settings = get_settings()

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Accept "Bearer <token>" format
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

    if not verify_token(token, settings):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return token


@auth_router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate with the app password and receive a session token."""
    settings = get_settings()

    if request.password != settings.app_password:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(settings)
    return LoginResponse(token=token)


@auth_router.post("/logout")
async def logout():
    """Logout endpoint — client should discard token."""
    # Stateless JWT — client discards the token
    return {"message": "Logged out"}
