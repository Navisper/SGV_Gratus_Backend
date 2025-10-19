from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from app.db.client import db
from app.core.security import hash_password, verify_password, create_access_token
import os, httpx, jwt

router = APIRouter()

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
    from urllib.parse import urlencode
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    return {"auth_url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}

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
async def google_callback_get(request: Request):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(400, "Falta parámetro 'code' de Google")

    # Reutilizamos la lógica del POST:
    # (puedes factorizarlo a una función interna si prefieres)
    import os, httpx, jwt
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
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
            await db.users.update(where={"id": user.id}, data={"google_sub": sub, "provider": "GOOGLE"})

    token = create_access_token(subject=user.id, role=(user.rol or "cajero"))
    return TokenResponse(access_token=token)
