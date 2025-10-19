from fastapi import APIRouter, Depends, Query
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

@router.get("/credits/overview", dependencies=[Depends(require_role("admin","cajero"))])
async def credits_overview():
    """
    Totales de cartera: total créditos, saldo pendiente, saldo vencido y distribución por estado.
    """
    q = """
    WITH base AS (
      SELECT total, saldo, status, (CASE WHEN saldo > 0 AND due_date < current_date THEN true ELSE false END) AS vencido
      FROM credits
    )
    SELECT
      COALESCE((SELECT SUM(total) FROM base),0) AS total_creditos,
      COALESCE((SELECT SUM(saldo) FROM base),0) AS saldo_pendiente,
      COALESCE((SELECT SUM(saldo) FROM base WHERE vencido = true),0) AS saldo_vencido,
      COALESCE(json_build_object(
        'open',    (SELECT COALESCE(SUM(saldo),0) FROM base WHERE status='open'),
        'partial', (SELECT COALESCE(SUM(saldo),0) FROM base WHERE status='partial'),
        'closed',  (SELECT COALESCE(SUM(saldo),0) FROM base WHERE status='closed'),
        'overdue', (SELECT COALESCE(SUM(saldo),0) FROM base WHERE status='overdue')
      ), '{}') AS por_estado
    ;
    """
    row = await db.query_first(q)  # type: ignore
    return row

@router.get("/credits/top-debtors", dependencies=[Depends(require_role("admin","cajero"))])
async def credits_top_debtors(limit: int = Query(10, ge=1, le=100)):
    """
    Top clientes por saldo pendiente (>0), descendente.
    """
    q = """
    SELECT cu.id as customer_id, cu.nombre,
           COALESCE(SUM(c.saldo),0) AS saldo_total,
           COUNT(*) as num_creditos
    FROM credits c
    JOIN customers cu ON cu.id = c.customer_id
    WHERE c.saldo > 0
    GROUP BY cu.id, cu.nombre
    ORDER BY saldo_total DESC
    LIMIT $1
    """
    rows = await db.query_raw(q, limit)  # type: ignore
    return rows

@router.get("/credits/upcoming-due", dependencies=[Depends(require_role("admin","cajero"))])
async def credits_upcoming_due(days: int = Query(7, ge=1, le=60)):
    """
    Créditos con saldo > 0 que vencen en los próximos N días (incluye hoy).
    """
    q = """
    SELECT c.id as credit_id, cu.id as customer_id, cu.nombre,
           c.saldo, c.due_date, c.status
    FROM credits c
    JOIN customers cu ON cu.id = c.customer_id
    WHERE c.saldo > 0
      AND c.due_date BETWEEN current_date AND current_date + ($1 || ' days')::interval
    ORDER BY c.due_date ASC
    """
    rows = await db.query_raw(q, days)  # type: ignore
    return rows