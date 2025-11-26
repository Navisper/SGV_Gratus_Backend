from fastapi import APIRouter, HTTPException, status, Request, Depends
from pydantic import BaseModel, EmailStr, Field
from fastapi.responses import RedirectResponse
from app.db.client import db
from app.core.security import hash_password, verify_password, create_access_token, get_current_user
import os, httpx, jwt, hmac, hashlib, secrets
from urllib.parse import urlencode, quote

router = APIRouter()

# ============================
# Environment variables
# ============================
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
STATE_SECRET = (os.getenv("OAUTH_STATE_SECRET") or os.getenv("SECRET_KEY") or "change-me").encode()

<<<<<<< HEAD
#metodo para mostrar estado 
=======
# ============================
# Helpers
# ============================
>>>>>>> 88246702dcda04257a8dbb62418d7b23af94b962
def _sign_state(nonce: str) -> str:
    sig = hmac.new(STATE_SECRET, nonce.encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{sig}"

def _verify_state(stored: str, received: str) -> bool:
    """Verifica que el parámetro `state` coincida con la cookie firmada."""
    return hmac.compare_digest(stored, received)

# ============================
# Modelos
# ============================
class RegisterRequest(BaseModel):
    nombre: str = Field(..., description="Nombre completo del usuario")
    email: EmailStr = Field(..., description="Correo electrónico válido")
    password: str = Field(..., description="Contraseña del usuario")
    rol: str = Field("admin", description="Rol del usuario. Por defecto: admin")

class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Correo electrónico registrado")
    password: str = Field(..., description="Contraseña asociada al usuario")

class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT emitido por el servidor")
    token_type: str = Field("bearer", description="Tipo de token (Bearer)")

class GoogleCallbackBody(BaseModel):
    code: str = Field(..., description="Código OAuth devuelto por Google")

# ============================
# Endpoints
# ============================

@router.post(
    "/register",
    response_model=TokenResponse,
    summary="Registrar un nuevo usuario",
    description="""
Crea un usuario nuevo con correo, nombre y contraseña.  
Si el correo ya existe, devuelve un error 400.  
Retorna un **token JWT** para iniciar sesión automáticamente.
""",
    responses={
        200: {"description": "Usuario registrado correctamente"},
        400: {"description": "Correo ya registrado"},
    }
)
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

# ------------------------------

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Iniciar sesión con email y contraseña",
    description="Autentica un usuario usando su correo y contraseña, retornando un token JWT.",
    responses={
        200: {"description": "Inicio de sesión exitoso"},
        401: {"description": "Credenciales inválidas"},
    }
)
async def login(req: LoginRequest):
    user = await db.users.find_unique(where={"email": req.email})
    if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

    token = create_access_token(subject=user.id, role=(user.rol or "cajero"))
    return TokenResponse(access_token=token)

# ------------------------------
# GOOGLE LOGIN
# ------------------------------

@router.get(
    "/google/login",
    summary="Iniciar autenticación con Google OAuth",
    description="""
Genera una URL de Google OAuth y redirige al usuario para iniciar sesión con Google.  
Crea y guarda un parámetro `state` en una cookie HttpOnly para proteger contra ataques CSRF.
"""
)
async def google_login():
    nonce = secrets.token_urlsafe(16)
    state = _sign_state(nonce)

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    resp = RedirectResponse(url=url, status_code=302)

    resp.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        samesite="lax",
        secure=False,
    )

    return resp

# ------------------------------

@router.post(
    "/google/callback",
    response_model=TokenResponse,
    summary="Procesar callback de Google OAuth (POST)",
    description="Intercambia el código OAuth por un token JWT del servidor.",
    responses={
        200: {"description": "Autenticación correcta"},
        400: {"description": "No se pudo procesar el código de Google"},
    }
)
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
            await db.users.update(where={"id": user.id}, data={"google_sub": sub, "provider": "GOOGLE"})

    token = create_access_token(subject=user.id, role=(user.rol or "cajero"))
    return TokenResponse(access_token=token)

# ------------------------------

@router.get(
    "/google/callback",
    summary="Procesar callback de Google OAuth (GET)",
    description="""
Ruta que Google llama directamente.  
Valida `state`, procesa el código y redirige al frontend con el token JWT.
"""
)
async def google_callback(request: Request):
    code = request.query_params.get("code")
    state_recv = request.query_params.get("state")
    state_cookie = request.cookies.get("oauth_state")

    if not code or not state_recv:
        raise HTTPException(400, "Faltan parámetros de Google (code/state).")

    if not state_cookie or not _verify_state(state_cookie, state_recv):
        raise HTTPException(400, "State inválido.")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })

        if token_resp.status_code != 200:
            return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=oauth_exchange_failed", status_code=302)

        token_json = token_resp.json()
        id_token = token_json.get("id_token")

        if not id_token:
            return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=missing_id_token", status_code=302)

        claims = jwt.decode(id_token, options={"verify_signature": False})
        email = claims.get("email")
        sub = claims.get("sub")
        name = claims.get("name") or "Usuario"

    if not email or not sub:
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=invalid_google_token", status_code=302)

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

    jwt_token = create_access_token(subject=user.id, role=(user.rol or "cajero"))
    resp = RedirectResponse(
        url=f"{FRONTEND_URL}/auth/callback?token={quote(jwt_token)}",
        status_code=302
    )

    resp.delete_cookie("oauth_state")
    return resp

# ------------------------------

@router.get(
    "/me",
    summary="Obtener datos del usuario autenticado",
    description="Retorna información del usuario usando el token JWT.",
    responses={
        200: {"description": "Información del usuario retornada exitosamente"},
        401: {"description": "Token inválido o ausente"},
    }
)
async def get_me(current_user=Depends(get_current_user)):
    return {
        "id": current_user.id,
        "nombre": current_user.nombre,
        "email": current_user.email,
        "rol": current_user.rol,
        "provider": current_user.provider,
        "created_at": current_user.created_at,
    }
