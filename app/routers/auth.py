from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from fastapi.responses import RedirectResponse
from app.db.client import db
from app.core.security import hash_password, verify_password, create_access_token
import os, httpx, jwt, hmac, hashlib, secrets
from urllib.parse import urlencode, quote

from app.db.client import db
from app.core.security import hash_password, verify_password, create_access_token

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
STATE_SECRET = (os.getenv("OAUTH_STATE_SECRET") or os.getenv("SECRET_KEY") or "change-me").encode()

def _sign_state(nonce: str) -> str:
    sig = hmac.new(STATE_SECRET, nonce.encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"

def _verify_state(stored: str, received: str) -> bool:
    # stored viene de cookie; received viene de query param
    return hmac.compare_digest(stored, received)

class RegisterRequest(BaseModel):
    nombre: str
    email: EmailStr
    password: str
    rol: str = "admin"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest):
    existing = await db.users.find_unique(where={"email": req.email})
    if existing:
        raise HTTPException(400, "Email ya registrado")
    user = await db.users.create(data={
        "nombre": req.nombre,
        "email": req.email,
        "password_hash": hash_password(req.password),
        "rol": req.rol,
        "provider": "LOCAL",
    })
    token = create_access_token(subject=user.id, role=(user.rol or "admin"))
    return TokenResponse(access_token=token)

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await db.users.find_unique(where={"email": req.email})
    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    token = create_access_token(subject=user.id, role=(user.rol or "cajero"))
    return TokenResponse(access_token=token)

# Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

@router.get("/google/login")
async def google_login():
    # Genera nonce y firma
    nonce = secrets.token_urlsafe(16)
    state = _sign_state(nonce)

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,  # importante para CSRF
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    # 302 al login de Google + cookie con state
    resp = RedirectResponse(url=url, status_code=302)
    # Cookie HttpOnly para que el front no pueda leerla (evita manipulación vía JS)
    resp.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        secure=False  # pon True si usas HTTPS
    )
    return resp

class GoogleCallbackBody(BaseModel):
    code: str

@router.post("/google/callback", response_model=TokenResponse)
async def google_callback(body: GoogleCallbackBody):
    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": body.code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            raise HTTPException(400, "No se pudo intercambiar el código de Google")
        token_json = token_resp.json()
        id_token = token_json.get("id_token")
        if not id_token:
            raise HTTPException(400, "Google no retornó id_token")
        claims = jwt.decode(id_token, options={"verify_signature": False})
        email = claims.get("email")
        sub = claims.get("sub")
        name = claims.get("name") or "Usuario"
    if not email or not sub:
        raise HTTPException(400, "Token de Google inválido")
    user = await db.users.find_unique(where={"email": email})
    if not user:
        admins = await db.users.find_many(where={"rol": "admin"}, take=1)
        role = "admin" if len(admins) == 0 else "cajero"
        user = await db.users.create(data={
            "nombre": name,
            "email": email,
            "provider": "GOOGLE",
            "google_sub": sub,
            "rol": role,
        })
    else:
        if not user.google_sub:
            await db.users.update(where={"id": user.id}, data={"google_sub": sub, "provider": "google"})
    token = create_access_token(subject=user.id, role=(user.rol or "cajero"))
    return TokenResponse(access_token=token)

@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(request: Request):
    # Google devolverá ?code=...&state=...
    code = request.query_params.get("code")
    state_recv = request.query_params.get("state")
    state_cookie = request.cookies.get("oauth_state")

    if not code or not state_recv:
        raise HTTPException(400, "Faltan parámetros de Google (code/state).")
    if not state_cookie or not _verify_state(state_cookie, state_recv):
        raise HTTPException(400, "State inválido.")

    # Intercambia code por tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            # Redirige al front con error
            to = f"{FRONTEND_URL}/auth/callback?error=oauth_exchange_failed"
            return RedirectResponse(url=to, status_code=302)

        token_json = token_resp.json()
        id_token = token_json.get("id_token")
        if not id_token:
            to = f"{FRONTEND_URL}/auth/callback?error=missing_id_token"
            return RedirectResponse(url=to, status_code=302)

        # En dev: sin verificar firma. En prod: valida JWKS de Google.
        claims = jwt.decode(id_token, options={"verify_signature": False})
        email = claims.get("email")
        sub = claims.get("sub")
        name = claims.get("name") or "Usuario"

    if not email or not sub:
        to = f"{FRONTEND_URL}/auth/callback?error=invalid_google_token"
        return RedirectResponse(url=to, status_code=302)

    # Busca/crea usuario
    user = await db.users.find_unique(where={"email": email})
    if not user:
        admins = await db.users.find_many(where={"rol": "admin"}, take=1)
        role = "admin" if len(admins) == 0 else "cajero"
        user = await db.users.create(data={
            "nombre": name,
            "email": email,
            "provider": "google",
            "google_sub": sub,
            "rol": role,
        })
    else:
        if not user.google_sub:
            await db.users.update(where={"id": user.id}, data={"google_sub": sub, "provider": "google"})

    # Emite tu JWT
    jwt_token = create_access_token(subject=user.id, role=(user.rol or "cajero"))

    # Opción A (rápida): redirigir con el token en la URL
    redirect_url = f"{FRONTEND_URL}/auth/callback?token={quote(jwt_token)}"

    # Opción B (más segura): setear cookie HttpOnly y redirigir sin token en URL
    # resp = RedirectResponse(url=f"{FRONTEND_URL}/auth/callback", status_code=302)
    # resp.set_cookie("access_token", jwt_token, httponly=True, samesite="lax", secure=False)
    # return resp

    # Limpia la cookie de state
    resp = RedirectResponse(url=redirect_url, status_code=302)
    resp.delete_cookie("oauth_state")
    return resp
