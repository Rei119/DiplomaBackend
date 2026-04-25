from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import JWTError, jwt
from typing import Optional
from urllib.parse import urlencode
import httpx
import secrets
import string
import time

from .. import crud, schemas, models
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

# Short-lived one-time codes for OAuth token exchange (code → JWT, expires in 60s)
_oauth_codes: dict[str, tuple[str, float]] = {}

def _issue_oauth_code(jwt_token: str) -> str:
    code = secrets.token_urlsafe(32)
    _oauth_codes[code] = (jwt_token, time.time() + 60)
    return code

def _redeem_oauth_code(code: str) -> Optional[str]:
    entry = _oauth_codes.pop(code, None)
    if entry is None:
        return None
    token, expires_at = entry
    if time.time() > expires_at:
        return None
    return token

# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = crud.get_user_by_username(db, username=username)
    if user is None:
        raise credentials_exception
    return user

# ── Auth endpoints ────────────────────────────────────────────────────────────

@router.post("/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_user(db=db, user=user)

@router.post("/login", response_model=schemas.Token)
def login(credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, username=credentials.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_registered")
    if not crud.verify_password(credentials.password, user.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer", "user": user}

@router.get("/me", response_model=schemas.UserResponse)
async def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user

@router.put("/me", response_model=schemas.UserResponse)
async def update_me(
    update_data: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if update_data.username and update_data.username != current_user.username:
        existing = crud.get_user_by_username(db, username=update_data.username)
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
    return crud.update_user(db=db, user=current_user, update_data=update_data)

# ── Google OAuth ──────────────────────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

def get_google_redirect_uri(request: Request) -> str:
    return f"{settings.BACKEND_URL.rstrip('/')}/api/auth/google/callback"

@router.get("/google")
async def google_login(request: Request, role: str = "student"):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    import base64, json
    state = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode()

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": get_google_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}")

@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str,
    state: str = "e30=",
    db: Session = Depends(get_db)
):
    import base64, json

    try:
        state_data = json.loads(base64.urlsafe_b64decode(state + "==").decode())
        role = state_data.get("role", "student")
    except Exception:
        role = "student"

    async with httpx.AsyncClient() as client:
        token_response = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "redirect_uri": get_google_redirect_uri(request),
            "grant_type": "authorization_code",
        })
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Google token exchange failed: {token_response.text}")
        token_data = token_response.json()

        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token_data['access_token']}"}
        )
        if userinfo_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get Google user info")
        google_user = userinfo_response.json()

    google_id = google_user.get("sub")
    email = google_user.get("email", "")
    full_name = google_user.get("name", "")

    base_username = email.split("@")[0].replace(".", "_").replace("-", "_").lower()[:20]

    user = crud.get_user_by_google_id(db, google_id=google_id)
    if not user:
        user = crud.get_user_by_email(db, email=email)
        if user:
            user = crud.link_google_account(db, user=user, google_id=google_id)
        else:
            username = base_username
            if crud.get_user_by_username(db, username=username):
                suffix = ''.join(secrets.choice(string.digits) for _ in range(4))
                username = f"{base_username}_{suffix}"
            user = crud.create_google_user(db, username=username, email=email, role=role, google_id=google_id, full_name=full_name)

    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    one_time_code = _issue_oauth_code(access_token)

    frontend_url = settings.FRONTEND_URL
    params = urlencode({
        "code": one_time_code,
        "username": user.username,
        "role": user.role,
        "id": user.id,
        "email": user.email or "",
        "full_name": user.full_name or "",
    })
    return RedirectResponse(url=f"{frontend_url}/auth/callback?{params}")


@router.post("/google/token")
async def exchange_oauth_code(payload: dict):
    """Exchange a one-time OAuth code for a JWT. Code expires in 60 seconds."""
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    token = _redeem_oauth_code(code)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return {"access_token": token, "token_type": "bearer"}
