import os, time, jwt
from typing import Optional
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from app.db.client import db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-super-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

class TokenData(BaseModel):
    sub: str
    role: str

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def create_access_token(*, subject: str, role: str, expires_in: Optional[int] = None) -> str:
    if expires_in is None:
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    now = int(time.time())
    payload = {"sub": subject, "role": role, "iat": now, "exp": now + expires_in}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise ValueError("bad token")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = await db.users.find_unique(where={"id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no existe")
    return user

def require_role(*roles: str):
    async def dependency(user=Depends(get_current_user)):
        if (user.rol or "cajero") not in roles:
            raise HTTPException(status_code=403, detail="Permisos insuficientes")
        return user
    return dependency
