from fastapi import APIRouter, Depends
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

@router.get("/summary")
async def summary(_=Depends(require_role("admin"))):
    q = "SELECT (SELECT COUNT(*) FROM products) AS num_productos, (SELECT COUNT(*) FROM sales) AS num_ventas, (SELECT COALESCE(SUM(total),0) FROM sales) AS total_vendido"
    row = await db.query_first(q)  # type: ignore
    return row

@router.get("/top-products")
async def top_products(limit: int = 10):
    q = """    SELECT p.codigo_unico, p.nombre,
    SUM(si.cantidad) AS unidades,
    SUM(si.subtotal) AS vendido,
    SUM((COALESCE(p.precio,0) - COALESCE(p.costo,0)) * si.cantidad) AS utilidad_estimada
    FROM sale_items si
    JOIN products p ON p.id = si.producto_id
    GROUP BY p.codigo_unico, p.nombre
    ORDER BY unidades DESC
    LIMIT $1
    """
    rows = await db.query_raw(q, limit)  # type: ignore
    return rows
