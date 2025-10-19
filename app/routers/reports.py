from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, date
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()

def _to_datestr(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if isinstance(d, date) else (d if d is None else str(d))

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

@router.get("/sales/timeseries", dependencies=[Depends(require_role("admin","cajero"))])
async def sales_timeseries(
    granularity: str = Query("day", regex="^(day|week|month)$"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    g = {"day":"day","week":"week","month":"month"}[granularity]
    d_from = _parse_date(date_from)
    d_to   = _parse_date(date_to)
    d_from_s = _to_datestr(d_from)
    d_to_s   = _to_datestr(d_to)

    q = f"""
    WITH bounds AS (
      SELECT
        COALESCE($1::date, (SELECT MIN(created_at)::date FROM sales)) AS dmin,
        COALESCE($2::date, current_date) AS dmax
    ),
    series AS (
      SELECT generate_series(dmin, dmax, '1 {g}'::interval)::date AS bucket_date
      FROM bounds
    ),
    summed AS (
      SELECT date_trunc('{g}', s.created_at)::date AS bucket_date,
             COUNT(*) AS num_ventas,
             COALESCE(SUM(s.total),0) AS total_vendido
      FROM sales s
      WHERE s.created_at::date BETWEEN (SELECT dmin FROM bounds) AND (SELECT dmax FROM bounds)
        AND COALESCE(s.anulada,false) = false
      GROUP BY 1
    )
    SELECT s.bucket_date::text AS bucket,
           COALESCE(sumd.total_vendido,0) AS total_vendido,
           COALESCE(sumd.num_ventas,0)     AS num_ventas
    FROM series s
    LEFT JOIN summed sumd USING (bucket_date)
    ORDER BY s.bucket_date;
    """
    rows = await db.query_raw(q, d_from_s, d_to_s)  # <-- strings
    return rows


@router.get("/credits/timeseries", dependencies=[Depends(require_role("admin","cajero"))])
async def credits_timeseries(
    granularity: str = Query("day", regex="^(day|week|month)$"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    g = {"day":"day","week":"week","month":"month"}[granularity]
    d_from = _parse_date(date_from)
    d_to   = _parse_date(date_to)
    
    """
    Serie temporal de cartera:
    - credit_issued: total de créditos creados en el período (sum(credits.total))
    - payments_received: total abonado en el período (sum(credit_payments.amount))
    - net_change: issued - payments
    - outstanding_end: saldo acumulado al fin de cada bucket (aprox = sum(issued) - sum(payments) acumulado)
    """
    g = {"day":"day","week":"week","month":"month"}[granularity]
    d_from = _parse_date(date_from)
    d_to   = _parse_date(date_to)

    q = f"""
    WITH bounds AS (
      SELECT
        COALESCE($1::date, LEAST(
          (SELECT MIN(created_at)::date FROM credits),
          (SELECT MIN(paid_at)::date FROM credit_payments)
        )) AS dmin,
        COALESCE($2::date, current_date) AS dmax
    ),
    series AS (
      SELECT generate_series(dmin, dmax, '1 {g}'::interval)::date AS bucket_date
      FROM bounds
    ),
    issued AS (
      SELECT date_trunc('{g}', c.created_at)::date AS bucket_date,
             COALESCE(SUM(c.total),0) AS credit_issued
      FROM credits c
      WHERE c.created_at::date BETWEEN (SELECT dmin FROM bounds) AND (SELECT dmax FROM bounds)
      GROUP BY 1
    ),
    paid AS (
      SELECT date_trunc('{g}', p.paid_at)::date AS bucket_date,
             COALESCE(SUM(p.amount),0) AS payments_received
      FROM credit_payments p
      WHERE p.paid_at::date BETWEEN (SELECT dmin FROM bounds) AND (SELECT dmax FROM bounds)
      GROUP BY 1
    ),
    merged AS (
      SELECT s.bucket_date,
             COALESCE(i.credit_issued,0)    AS credit_issued,
             COALESCE(p.payments_received,0) AS payments_received
      FROM series s
      LEFT JOIN issued i USING (bucket_date)
      LEFT JOIN paid   p USING (bucket_date)
      ORDER BY s.bucket_date
    ),
    running AS (
      SELECT bucket_date::text AS bucket,
             credit_issued,
             payments_received,
             (credit_issued - payments_received) AS net_change,
             SUM(credit_issued - payments_received)
               OVER (ORDER BY bucket_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS outstanding_end
      FROM merged
    )
    SELECT * FROM running;
    """
    rows = await db.query_raw(q, d_from, d_to)  # type: ignore
    return rows


@router.get("/credits/repayment-rate", dependencies=[Depends(require_role("admin","cajero"))])
async def credits_repayment_rate(
    granularity: str = Query("month", regex="^(month|week|day)$"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    g = {"day":"day","week":"week","month":"month"}[granularity]
    d_from = _parse_date(date_from)
    d_to   = _parse_date(date_to)
    """
    Tasa de recuperación = pagos / créditos emitidos por período.
    Para períodos sin emisión, devuelve 0.
    """
    g = {"day":"day","week":"week","month":"month"}[granularity]
    d_from = _parse_date(date_from)
    d_to   = _parse_date(date_to)

    q = f"""
    WITH bounds AS (
      SELECT
        COALESCE($1::date, LEAST(
          (SELECT MIN(created_at)::date FROM credits),
          (SELECT MIN(paid_at)::date FROM credit_payments)
        )) AS dmin,
        COALESCE($2::date, current_date) AS dmax
    ),
    series AS (
      SELECT generate_series(dmin, dmax, '1 {g}'::interval)::date AS bucket_date
      FROM bounds
    ),
    issued AS (
      SELECT date_trunc('{g}', c.created_at)::date AS bucket_date,
             COALESCE(SUM(c.total),0) AS credit_issued
      FROM credits c
      WHERE c.created_at::date BETWEEN (SELECT dmin FROM bounds) AND (SELECT dmax FROM bounds)
      GROUP BY 1
    ),
    paid AS (
      SELECT date_trunc('{g}', p.paid_at)::date AS bucket_date,
             COALESCE(SUM(p.amount),0) AS payments_received
      FROM credit_payments p
      WHERE p.paid_at::date BETWEEN (SELECT dmin FROM bounds) AND (SELECT dmax FROM bounds)
      GROUP BY 1
    ),
    merged AS (
      SELECT s.bucket_date,
             COALESCE(i.credit_issued,0) AS credit_issued,
             COALESCE(p.payments_received,0) AS payments_received
      FROM series s
      LEFT JOIN issued i USING (bucket_date)
      LEFT JOIN paid   p USING (bucket_date)
      ORDER BY s.bucket_date
    )
    SELECT bucket_date::text AS bucket,
           credit_issued,
           payments_received,
           CASE WHEN credit_issued > 0 THEN ROUND((payments_received / credit_issued)::numeric, 4) ELSE 0 END AS repayment_rate
    FROM merged;
    """
    rows = await db.query_raw(q, d_from, d_to)  # type: ignore
    return rows