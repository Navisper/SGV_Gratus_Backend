from fastapi import APIRouter, HTTPException, Depends, Query, status
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, Field, validator
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

# ---------------------------
# Pydantic Schemas (input)
# ---------------------------

class SaleItemIn(BaseModel):
    codigo_unico: str = Field(..., min_length=1)
    cantidad: int = Field(..., gt=0)
    precio_unitario: float = Field(..., gt=0)

class SaleCreate(BaseModel):
    usuario_id: Optional[str] = None
    tienda_id: Optional[str] = None
    metodo_pago: str = Field(..., min_length=1)  # efectivo|tarjeta|transferencia|etc
    descuento: float = Field(0, ge=0)
    items: List[SaleItemIn]

    @validator("items")
    def validate_items(cls, v):
        if not v or len(v) == 0:
            raise ValueError("Debe incluir items de venta")
        return v

# ---------------------------
# Helpers
# ---------------------------

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()

# ---------------------------
# Endpoints
# ---------------------------

@router.post("/", dependencies=[Depends(require_role("admin","cajero"))])
async def create_sale(payload: SaleCreate):
    codes = [i.codigo_unico for i in payload.items]
    prods = await db.products.find_many(where={"codigo_unico": {"in": codes}})
    pmap = {p.codigo_unico: p for p in prods}

    for it in payload.items:
        p = pmap.get(it.codigo_unico)
        if not p:
            raise HTTPException(400, f"Producto no existe: {it.codigo_unico}")
        if (p.stock or 0) < it.cantidad:
            raise HTTPException(400, f"Stock insuficiente para {p.nombre} ({p.codigo_unico})")

    subtotal = sum(it.precio_unitario * it.cantidad for it in payload.items)
    total = subtotal - float(payload.descuento or 0)
    if total < 0:
        raise HTTPException(400, "El total no puede ser negativo")

    sale_data: Dict[str, Any] = {
        "metodo_pago": payload.metodo_pago,
        "descuento": payload.descuento,
        "total": total,
    }
    # incluir solo si vienen
    if payload.usuario_id: sale_data["usuario_id"] = payload.usuario_id
    if payload.tienda_id:  sale_data["tienda_id"]  = payload.tienda_id

    async with db.tx() as tx:
        sale = await tx.sales.create(data=sale_data)
        for it in payload.items:
            p = pmap[it.codigo_unico]
            await tx.sale_items.create(data={
                "venta_id": sale.id,
                "producto_id": p.id,
                "cantidad": it.cantidad,
                "precio_unitario": it.precio_unitario,
                "subtotal": it.precio_unitario * it.cantidad
            })
            await tx.products.update(where={"id": p.id}, data={"stock": (p.stock - it.cantidad)})

    return {"ok": True, "sale_id": sale.id, "subtotal": subtotal, "descuento": float(payload.descuento or 0), "total": total}


@router.get("/{sale_id}", dependencies=[Depends(require_role("admin","cajero"))])
async def get_sale(sale_id: str):
    """
    Trae la venta y sus items con datos de producto.
    """
    # Validar que el sale_id no sea "undefined" o vacío
    if not sale_id or sale_id == "undefined":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sale ID is required"
        )
    
    # Validar formato UUID
    try:
        sale_uuid = UUID(sale_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sale ID format"
        )
    
    # Consulta SQL con cast explícito a UUID
    q = """
    SELECT
      s.id, s.usuario_id, s.tienda_id, s.metodo_pago, s.descuento, s.total, s.created_at, COALESCE(s.anulada,false) as anulada,
      COALESCE(json_agg(json_build_object(
        'id', si.id,
        'producto_id', si.producto_id,
        'codigo_unico', p.codigo_unico,
        'nombre', p.nombre,
        'cantidad', si.cantidad,
        'precio_unitario', si.precio_unitario,
        'subtotal', si.subtotal
      ) ORDER BY si.id) FILTER (WHERE si.id IS NOT NULL), '[]') AS items
    FROM sales s
    LEFT JOIN sale_items si ON si.venta_id = s.id
    LEFT JOIN products p ON p.id = si.producto_id
    WHERE s.id = $1::uuid  -- CAST EXPLÍCITO A UUID
    GROUP BY s.id
    """
    
    try:
        rows = await db.query_raw(q, str(sale_uuid))  # type: ignore
        if not rows:
            raise HTTPException(status_code=404, detail="Venta no encontrada")
        return rows[0]
    except Exception as e:
        # Log del error para debugging
        print(f"Error en get_sale: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )


@router.get("/", dependencies=[Depends(require_role("admin","cajero"))])
async def list_sales(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str]   = Query(None, description="YYYY-MM-DD (inclusive)"),
    tienda_id: Optional[str] = None,
    usuario_id: Optional[str] = None,
    metodo_pago: Optional[str] = None,
    anulada: Optional[bool] = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Lista ventas con filtros y paginación.
    """
    # Construcción dinámica de filtros
    filters = []
    params: List[Any] = []

    if date_from:
        filters.append("s.created_at::date >= $%s" % (len(params)+1))
        params.append(_parse_date(date_from))
    if date_to:
        filters.append("s.created_at::date <= $%s" % (len(params)+1))
        params.append(_parse_date(date_to))
    if tienda_id:
        filters.append("s.tienda_id = $%s" % (len(params)+1))
        params.append(tienda_id)
    if usuario_id:
        filters.append("s.usuario_id = $%s" % (len(params)+1))
        params.append(usuario_id)
    if metodo_pago:
        filters.append("s.metodo_pago = $%s" % (len(params)+1))
        params.append(metodo_pago)
    if anulada is not None:
        filters.append("COALESCE(s.anulada,false) = $%s" % (len(params)+1))
        params.append(anulada)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params += [limit, offset]

    q = f"""
    SELECT
      s.id, s.usuario_id, s.tienda_id, s.metodo_pago, s.descuento, s.total, s.created_at, COALESCE(s.anulada,false) AS anulada
    FROM sales s
    {where}
    ORDER BY s.created_at DESC
    LIMIT ${len(params)-1} OFFSET ${len(params)}
    """
    rows = await db.query_raw(q, *params)  # type: ignore
    return rows


@router.get("/kpi/daily", dependencies=[Depends(require_role("admin","cajero"))])
async def kpi_daily(day: Optional[str] = Query(None, description="YYYY-MM-DD; por defecto hoy")):
    """
    KPIs del día: #ventas, total vendido, total por método de pago y top 5 productos.
    """
    if day:
        d = _parse_date(day)
    else:
        d = datetime.now().date()

    # Totales básicos y por método
    q1 = """
    WITH base AS (
      SELECT * FROM sales
      WHERE created_at::date = $1 AND COALESCE(anulada,false) = false
    )
    SELECT
      (SELECT COUNT(*) FROM base) AS num_ventas,
      COALESCE((SELECT SUM(total) FROM base), 0) AS total_vendido
    """
    head = await db.query_first(q1, d)  # type: ignore

    q2 = """
    SELECT metodo_pago, COALESCE(SUM(total),0) AS total
    FROM sales
    WHERE created_at::date = $1 AND COALESCE(anulada,false) = false
    GROUP BY 1
    ORDER BY 2 DESC
    """
    by_method = await db.query_raw(q2, d)  # type: ignore

    q3 = """
    SELECT p.codigo_unico, p.nombre, SUM(si.cantidad) AS unidades, SUM(si.subtotal) AS vendido
    FROM sale_items si
    JOIN sales s ON s.id = si.venta_id
    JOIN products p ON p.id = si.producto_id
    WHERE s.created_at::date = $1 AND COALESCE(s.anulada,false) = false
    GROUP BY p.codigo_unico, p.nombre
    ORDER BY unidades DESC
    LIMIT 5
    """
    top_products = await db.query_raw(q3, d)  # type: ignore

    return {"day": str(d), "head": head, "by_method": by_method, "top_products": top_products}


@router.get("/close/day", dependencies=[Depends(require_role("admin","cajero"))])
async def close_day(day: Optional[str] = Query(None, description="YYYY-MM-DD; por defecto hoy")):
    """
    Resumen de cierre de día:
    - Ventas, total, total por método
    - Productos vendidos (cantidades y total)
    - Descuentos totales
    """
    if day:
        d = _parse_date(day)
    else:
        d = datetime.now().date()

    q_head = """
    SELECT
      COUNT(*) AS num_ventas,
      COALESCE(SUM(total),0) AS total_vendido,
      COALESCE(SUM(descuento),0) AS descuentos
    FROM sales
    WHERE created_at::date = $1 AND COALESCE(anulada,false) = false
    """
    head = await db.query_first(q_head, d)  # type: ignore

    q_pay = """
    SELECT metodo_pago, COALESCE(SUM(total),0) AS total
    FROM sales
    WHERE created_at::date = $1 AND COALESCE(anulada,false) = false
    GROUP BY 1
    ORDER BY 2 DESC
    """
    by_method = await db.query_raw(q_pay, d)  # type: ignore

    q_items = """
    SELECT p.codigo_unico, p.nombre,
           SUM(si.cantidad) AS unidades,
           SUM(si.subtotal) AS vendido
    FROM sale_items si
    JOIN sales s ON s.id = si.venta_id
    JOIN products p ON p.id = si.producto_id
    WHERE s.created_at::date = $1 AND COALESCE(s.anulada,false) = false
    GROUP BY p.codigo_unico, p.nombre
    ORDER BY unidades DESC
    """
    items = await db.query_raw(q_items, d)  # type: ignore

    return {"day": str(d), "summary": head, "by_method": by_method, "items": items}


@router.post("/{sale_id}/cancel", dependencies=[Depends(require_role("admin"))])
async def cancel_sale(sale_id: str):
    """
    Anula una venta:
    - Si ya está anulada, devuelve 409.
    - Restaura stock de todos los items.
    - Marca sales.anulada = true
    """
    # Validar que el sale_id no sea "undefined" o vacío
    if not sale_id or sale_id == "undefined":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sale ID is required"
        )
    
    # Validar formato UUID
    try:
        sale_uuid = UUID(sale_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sale ID format"
        )
    
    # Usar el UUID validado
    sale_id_str = str(sale_uuid)
    
    sale = await db.sales.find_unique(where={"id": sale_id_str})
    if not sale:
        raise HTTPException(404, "Venta no encontrada")
    if getattr(sale, "anulada", False):
        raise HTTPException(status_code=409, detail="La venta ya está anulada")

    # Traer items de venta
    items = await db.sale_items.find_many(where={"venta_id": sale_id_str})
    if not items:
        raise HTTPException(400, "Venta sin items, no se puede anular correctamente")

    # Restaurar stock en transacción
    async with db.tx() as tx:
        # Restaurar stock
        for it in items:
            prod = await tx.products.find_unique(where={"id": it.producto_id})
            if not prod:
                raise HTTPException(400, f"Producto no encontrado para item {it.id}")
            await tx.products.update(
                where={"id": prod.id},
                data={"stock": (prod.stock or 0) + it.cantidad}
            )
        # Marcar anulado
        await tx.sales.update(where={"id": sale_id_str}, data={"anulada": True})

    return {"ok": True, "sale_id": sale_id_str, "message": "Venta anulada y stock restaurado"}

