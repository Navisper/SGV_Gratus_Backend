from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel, EmailStr
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

# Schema actualizado para coincidir con la base de datos
class CustomerIn(BaseModel):
    nombre: str
    telefono: Optional[str] = None
    email: Optional[EmailStr] = None
    direccion: Optional[str] = None

# Schema para respuesta - incluir solo campos que existen
class CustomerResponse(BaseModel):
    id: str
    nombre: str
    telefono: Optional[str]
    email: Optional[str]
    direccion: Optional[str]
    created_at: Optional[str]  # Convertir datetime a string

    class Config:
        from_attributes = True

@router.post("/", response_model=CustomerResponse)
async def create_customer(body: CustomerIn, _=Depends(require_role("admin","cajero"))):
    customer = await db.customers.create(data=body.dict())
    # Convertir datetime a string para la respuesta
    if customer.created_at:
        customer.created_at = customer.created_at.isoformat()
    return customer

@router.get("/", response_model=List[CustomerResponse])
async def list_customers(
    q: Optional[str] = Query(None), 
    take: int = 50, 
    skip: int = 0,
    _=Depends(require_role("admin","cajero"))
):
    if q:
        customers = await db.customers.find_many(
            where={
                "OR": [
                    {"nombre": {"contains": q, "mode": "insensitive"}},
                    {"email": {"contains": q, "mode": "insensitive"}},
                    {"telefono": {"contains": q, "mode": "insensitive"}},
                ]
            },
            take=take, 
            skip=skip, 
            order={"created_at": "desc"}
        )
    else:
        customers = await db.customers.find_many(
            take=take, 
            skip=skip, 
            order={"created_at": "desc"}
        )
    
    # Convertir datetime a string para cada customer
    for customer in customers:
        if customer.created_at:
            customer.created_at = customer.created_at.isoformat()
    
    return customers

@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: str, _=Depends(require_role("admin","cajero"))):
    customer = await db.customers.find_unique(where={"id": customer_id})
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    if customer.created_at:
        customer.created_at = customer.created_at.isoformat()
    
    return customer

@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str, 
    body: CustomerIn, 
    _=Depends(require_role("admin","cajero"))
):
    # Verificar que el cliente existe
    existing_customer = await db.customers.find_unique(where={"id": customer_id})
    if not existing_customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    customer = await db.customers.update(
        where={"id": customer_id}, 
        data=body.dict(exclude_unset=True)
    )
    
    if customer.created_at:
        customer.created_at = customer.created_at.isoformat()
    
    return customer

@router.delete("/{customer_id}")
async def delete_customer(customer_id: str, _=Depends(require_role("admin"))):
    # Verificar que el cliente existe
    existing_customer = await db.customers.find_unique(where={"id": customer_id})
    if not existing_customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    await db.customers.delete(where={"id": customer_id})
    return {"ok": True, "message": "Cliente eliminado exitosamente"}