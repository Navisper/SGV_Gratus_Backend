from fastapi import APIRouter, HTTPException
from db.client import db

router = APIRouter()

@router.get("/")
async def listar_productos():
    return await db.product.find_many()

@router.post("/")
async def crear_producto(producto: dict):
    nuevo = await db.product.create(data=producto)
    return nuevo

@router.get("/{codigo}")
async def obtener_producto(codigo: str):
    producto = await db.product.find_unique(where={"codigoUnico": codigo})
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return producto

@router.put("/{codigo}")
async def actualizar_producto(codigo: str, data: dict):
    return await db.product.update(where={"codigoUnico": codigo}, data=data)

@router.delete("/{codigo}")
async def eliminar_producto(codigo: str):
    return await db.product.delete(where={"codigoUnico": codigo})
