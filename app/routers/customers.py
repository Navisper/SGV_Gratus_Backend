from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel, EmailStr
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

class CustomerIn(BaseModel):
  nombre: str
  telefono: Optional[str] = None
  email: Optional[EmailStr] = None
  direccion: Optional[str] = None

@router.post("/", dependencies=[Depends(require_role("admin","cajero"))])
async def create_customer(body: CustomerIn):
  return await db.customers.create(data=body.dict())

@router.get("/", dependencies=[Depends(require_role("admin","cajero"))])
async def list_customers(q: Optional[str] = Query(None), take: int = 50, skip: int = 0):
  if q:
    return await db.customers.find_many(
      where={"OR":[
        {"nombre": {"contains": q, "mode": "insensitive"}},
        {"email": {"contains": q, "mode": "insensitive"}},
        {"telefono": {"contains": q, "mode": "insensitive"}},
      ]},
      take=take, skip=skip, order={"created_at": "desc"}
    )
  return await db.customers.find_many(take=take, skip=skip, order={"created_at": "desc"})
