from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional, Any
from datetime import datetime, date
from pydantic import BaseModel, Field, validator
from app.db.client import db
from app.core.security import require_role
from fastapi.responses import StreamingResponse, PlainTextResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
import io, csv

router = APIRouter()

# =========================================================
#                     SCHEMAS
# =========================================================

class CreditSaleItem(BaseModel):
    """Item individual dentro de una venta a crédito."""
    codigo_unico: str = Field(..., description="Código único del producto")
    cantidad: int = Field(..., gt=0, description="Cantidad vendida")
    precio_unitario: float = Field(..., gt=0, description="Precio por unidad")

class CreditSaleCreate(BaseModel):
    """Payload para crear una venta a crédito."""
    customer_id: str = Field(..., description="ID del cliente")
    usuario_id: Optional[str] = Field(None, description="ID del usuario que genera la venta (opcional)")
    tienda_id: Optional[str] = Field(None, description="ID de la tienda donde se genera la venta")
    metodo_pago: str = Field("credito", description="Método de pago (fijo: crédito)")
    descuento: float = Field(0, description="Descuento aplicado a la venta")
    due_date: date = Field(..., description="Fecha de vencimiento del crédito")
    items: List[CreditSaleItem] = Field(..., description="Lista de productos vendidos")

    @validator("items")
    def _items_not_empty(cls, v):
        if not v:
            raise ValueError("Debe incluir items")
        return v

class PaymentIn(BaseModel):
    """Abono realizado a un crédito."""
    amount: float = Field(..., gt=0, description="Monto pagado")
    metodo_pago: str = Field("efectivo", description="Método de pago utilizado")
    notes: Optional[str] = Field(None, description="Notas opcionales para el pago")
    usuario_id: Optional[str] = Field(None, description="ID del usuario que registra el pago")

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


# =========================================================
#                     ENDPOINTS
# =========================================================

@router.post(
    "/sales",
    summary="Crear una venta a crédito",
    description="""
Crea una venta con método **crédito**, descuenta inventario, crea registros de items y genera un crédito asociado.  
Valida stock, totales y calcula saldo inicial.
    """,
    responses={
        200: {"description": "Venta a crédito creada correctamente"},
        400: {"description": "Error en validaciones: producto inexistente, stock insuficiente o total inválido"},
        403: {"description": "Usuario sin permisos (solo admin/cajero)"},
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def create_credit_sale(body: CreditSaleCreate):
    codes = [i.codigo_unico for i in body.items]
    prods = await db.products.find_many(where={"codigo_unico": {"in": codes}})
    pmap = {p.codigo_unico: p for p in prods}

    # Validaciones
    for it in body.items:
        p = pmap.get(it.codigo_unico)
        if not p:
            raise HTTPException(400, f"Producto no existe: {it.codigo_unico}")
        if (p.stock or 0) < it.cantidad:
            raise HTTPException(400, f"Stock insuficiente para {p.nombre} ({it.codigo_unico})")

    subtotal = sum(it.precio_unitario * it.cantidad for it in body.items)
    total = subtotal - float(body.descuento or 0)

    if total <= 0:
        raise HTTPException(400, "El total debe ser mayor a 0")

    sale_data = {
        "metodo_pago": "credito",
        "descuento": body.descuento,
        "total": total
    }
    if body.usuario_id:
        sale_data["usuario_id"] = body.usuario_id
    if body.tienda_id:
        sale_data["tienda_id"] = body.tienda_id

    # Transacción
    async with db.tx() as tx:
        sale = await tx.sales.create(data=sale_data)

        for it in body.items:
            p = pmap[it.codigo_unico]

            await tx.sale_items.create(data={
                "venta_id": sale.id,
                "producto_id": p.id,
                "cantidad": it.cantidad,
                "precio_unitario": it.precio_unitario,
                "subtotal": it.precio_unitario * it.cantidad,
            })

            await tx.products.update(
                where={"id": p.id},
                data={"stock": (p.stock - it.cantidad)}
            )

        credit = await tx.credits.create(data={
            "sale_id": sale.id,
            "customer_id": body.customer_id,
            "total": total,
            "saldo": total,
            "due_date": body.due_date,
            "status": "open"
        })

    return {
        "ok": True,
        "sale_id": sale.id,
        "credit_id": credit.id,
        "total": total,
        "saldo": total
    }


@router.get(
    "/",
    summary="Listar créditos",
    description="""
Filtra créditos por cliente, estado, vencidos, fechas y paginación.  
Devuelve lista cruda desde SQL.
""",
    responses={200: {"description": "Listado de créditos"}},
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def list_credits(
    customer_id: Optional[str] = None,
    status: Optional[str] = Query(None, description="open|partial|closed|overdue"),
    overdue: Optional[bool] = Query(None, description="true para solo vencidos"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    filters = []
    params: List[Any] = []

    if customer_id:
        filters.append(f"c.customer_id = ${len(params)+1}")
        params.append(customer_id)

    if status:
        filters.append(f"c.status = ${len(params)+1}")
        params.append(status)

    if overdue is True:
        filters.append("c.saldo > 0 AND c.due_date < current_date")

    if date_from:
        filters.append(f"c.created_at::date >= ${len(params)+1}")
        params.append(_parse_date(date_from))

    if date_to:
        filters.append(f"c.created_at::date <= ${len(params)+1}")
        params.append(_parse_date(date_to))

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params += [limit, offset]

    q = f"""
    SELECT c.id, c.sale_id, c.customer_id, cu.nombre as customer_nombre,
           c.total, c.saldo, c.due_date, c.status, c.created_at
    FROM credits c
    JOIN customers cu ON cu.id = c.customer_id
    {where}
    ORDER BY c.created_at DESC
    LIMIT ${len(params)-1} OFFSET ${len(params)}
    """

    return await db.query_raw(q, *params)


@router.get(
    "/{credit_id}",
    summary="Obtener un crédito por ID",
    description="Devuelve datos del crédito, cliente y pagos realizados.",
    responses={
        200: {"description": "Crédito encontrado"},
        404: {"description": "Crédito no encontrado"}
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def get_credit(credit_id: str):
    q = """
    SELECT c.id, c.sale_id, c.customer_id, cu.nombre as customer_nombre,
           c.total, c.saldo, c.due_date, c.status, c.created_at,
           COALESCE(json_agg(json_build_object(
             'id', p.id,
             'amount', p.amount,
             'metodo_pago', p.metodo_pago,
             'notes', p.notes,
             'paid_at', p.paid_at,
             'usuario_id', p.usuario_id
           ) ORDER BY p.paid_at) FILTER (WHERE p.id IS NOT NULL), '[]') as payments
    FROM credits c
    JOIN customers cu ON cu.id = c.customer_id
    LEFT JOIN credit_payments p ON p.credit_id = c.id
    WHERE c.id = $1
    GROUP BY c.id, cu.nombre
    """

    rows = await db.query_raw(q, credit_id)
    if not rows:
        raise HTTPException(404, "Crédito no encontrado")

    return rows[0]


@router.post(
    "/{credit_id}/payments",
    summary="Registrar un pago a un crédito",
    description="Crea un abono y actualiza el saldo y el estado del crédito.",
    responses={
        200: {"description": "Pago registrado"},
        400: {"description": "Monto inválido o mayor al saldo"},
        404: {"description": "Crédito no encontrado"},
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def add_payment(credit_id: str, body: PaymentIn):
    credit = await db.credits.find_unique(where={"id": credit_id})

    if not credit:
        raise HTTPException(404, "Crédito no encontrado")
    if float(credit.saldo) <= 0:
        raise HTTPException(400, "El crédito ya está saldado")

    amount = float(body.amount)

    if amount > float(credit.saldo):
        raise HTTPException(400, f"Abono mayor al saldo ({credit.saldo})")

    nuevo_saldo = float(credit.saldo) - amount
    new_status = "closed" if nuevo_saldo == 0 else ("overdue" if (credit.due_date < date.today()) else "partial")

    async with db.tx() as tx:
        pay = await tx.credit_payments.create(data={
            "credit_id": credit_id,
            "usuario_id": body.usuario_id,
            "amount": amount,
            "metodo_pago": body.metodo_pago,
            "notes": body.notes
        })

        await tx.credits.update(
            where={"id": credit_id},
            data={"saldo": nuevo_saldo, "status": new_status}
        )

    return {
        "ok": True,
        "payment_id": pay.id,
        "nuevo_saldo": nuevo_saldo,
        "status": new_status
    }


@router.get(
    "/aging/report",
    summary="Reporte de antigüedad de saldos (Aging)",
    description="Retorna totales agrupados en buckets: current, 0–30, 31–60, 61–90, 90+ días.",
    responses={200: {"description": "Reporte generado"}},
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def aging_report():
    q = """
    SELECT
      sum(case when c.saldo > 0 and c.due_date >= current_date then c.saldo else 0 end) as current,
      sum(case when c.saldo > 0 and c.due_date < current_date and current_date - c.due_date <= 30 then c.saldo else 0 end) as "0_30",
      sum(case when c.saldo > 0 and current_date - c.due_date between 31 and 60 then c.saldo else 0 end) as "31_60",
      sum(case when c.saldo > 0 and current_date - c.due_date between 61 and 90 then c.saldo else 0 end) as "61_90",
      sum(case when c.saldo > 0 and current_date - c.due_date > 90 then c.saldo else 0 end) as "90_plus"
    FROM credits c;
    """
    return await db.query_first(q)


@router.get(
    "/customers/{customer_id}/statement",
    summary="Estado de cuenta de un cliente",
    description="Devuelve créditos, saldos y pagos asociados al cliente.",
    responses={
        200: {"description": "Estado de cuenta generado"},
        404: {"description": "Cliente no encontrado"}
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def customer_statement(customer_id: str):
    q = """
    SELECT
      cu.id as customer_id, cu.nombre,
      COALESCE(json_agg(json_build_object(
        'credit_id', c.id,
        'sale_id', c.sale_id,
        'total', c.total,
        'saldo', c.saldo,
        'due_date', c.due_date,
        'status', c.status,
        'payments', (
          SELECT COALESCE(json_agg(json_build_object(
            'id', p.id, 'amount', p.amount, 'paid_at', p.paid_at,
            'metodo_pago', p.metodo_pago, 'notes', p.notes
          ) ORDER BY p.paid_at) FILTER (WHERE p.id IS NOT NULL), '[]')
          FROM credit_payments p WHERE p.credit_id = c.id
        )
      ) ORDER BY c.created_at DESC) FILTER (WHERE c.id IS NOT NULL), '[]') AS credits
    FROM customers cu
    LEFT JOIN credits c ON c.customer_id = cu.id
    WHERE cu.id = $1
    GROUP BY cu.id, cu.nombre
    """
    rows = await db.query_raw(q, customer_id)
    if not rows:
        raise HTTPException(404, "Cliente no encontrado")
    return rows[0]


@router.get(
    "/customers/{customer_id}/statement.csv",
    summary="Exportar estado de cuenta a CSV",
    description="Genera un archivo CSV descargable con los créditos del cliente.",
    responses={
        200: {"description": "CSV generado"},
        404: {"description": "Cliente no encontrado"},
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def customer_statement_csv(customer_id: str):
    data = await customer_statement(customer_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Cliente", data["nombre"]])
    writer.writerow([])
    writer.writerow(["credit_id", "sale_id", "total", "saldo", "due_date", "status", "payments_count", "payments_total"])

    for c in data["credits"]:
        pays = c.get("payments") or []
        total_pays = sum(float(p.get("amount", 0) or 0) for p in pays)

        writer.writerow([
            c["credit_id"], c["sale_id"], c["total"], c["saldo"], c["due_date"],
            c["status"], len(pays), total_pays
        ])

    resp = PlainTextResponse(buf.getvalue(), media_type="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="estado_cuenta_{customer_id}.csv"'
    return resp


@router.get(
    "/customers/{customer_id}/statement.pdf",
    summary="Exportar estado de cuenta a PDF",
    description="Genera un PDF sencillo con los créditos y pagos del cliente.",
    responses={
        200: {"description": "PDF generado"},
        404: {"description": "Cliente no encontrado"},
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def customer_statement_pdf(customer_id: str):
    data = await customer_statement(customer_id)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 2 * cm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, y, f"Estado de Cuenta - {data['nombre']}")
    y -= 1 * cm

    c.setFont("Helvetica", 10)

    for cred in data["credits"]:
        if y < 3 * cm:
            c.showPage()
            y = height - 2 * cm
            c.setFont("Helvetica", 10)

        c.drawString(
            2 * cm,
            y,
            f"Crédito: {cred['credit_id']} | Venta: {cred['sale_id']} | Total: {cred['total']} | "
            f"Saldo: {cred['saldo']} | Vence: {cred['due_date']} | Estado: {cred['status']}"
        )
        y -= 0.6 * cm

        pays = cred.get("payments") or []
        if not pays:
            c.drawString(2.5 * cm, y, "- Sin pagos")
            y -= 0.5 * cm
        else:
            for p in pays:
                if y < 3 * cm:
                    c.showPage()
                    y = height - 2 * cm
                    c.setFont("Helvetica", 10)

                c.drawString(
                    2.5 * cm,
                    y,
                    f"• Pago {p['id']} | {p['paid_at']} | {p['metodo_pago']} | ${p['amount']} | {p.get('notes','') or ''}"
                )
                y -= 0.5 * cm

        y -= 0.2 * cm

    c.showPage()
    c.save()
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="estado_cuenta_{customer_id}.pdf"'
        }
    )
