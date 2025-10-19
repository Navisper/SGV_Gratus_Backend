from fastapi import APIRouter, Depends, HTTPException
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

@router.get("/")
async def list_products(skip: int = 0, take: int = 100, _=Depends(require_role("admin","cajero"))):
    return await db.products.find_many(skip=skip, take=take, order={"created_at": "desc"})

@router.get("/{codigo_unico}")
async def get_by_code(codigo_unico: str, _=Depends(require_role("admin","cajero"))):
    prod = await db.products.find_unique(where={"codigo_unico": codigo_unico})
    if not prod:
        raise HTTPException(404, "Producto no encontrado")
    return prod

@router.post("/")
async def create_product(data: dict, _=Depends(require_role("admin","cajero"))):
    return await db.products.create(data=data)

@router.put("/{codigo_unico}")
async def update_product(codigo_unico: str, data: dict, _=Depends(require_role("admin","cajero"))):
    return await db.products.update(where={"codigo_unico": codigo_unico}, data=data)

@router.delete("/{codigo_unico}")
async def delete_product(codigo_unico: str, _=Depends(require_role("admin","cajero"))):
    return await db.products.delete(where={"codigo_unico": codigo_unico})
