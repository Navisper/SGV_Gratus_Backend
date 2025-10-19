from fastapi import APIRouter, HTTPException, Depends
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

async def _next_invoice_number():
    row = await db.query_first("SELECT COALESCE(MAX(consecutivo),0)+1 AS next FROM invoices")  # type: ignore
    return int(row["next"]) if row and "next" in row else 1

@router.post("/{sale_id}")
async def generate_invoice(sale_id: str, _=Depends(require_role("admin"))):
    sale = await db.sales.find_unique(where={"id": sale_id}, include={"items": True})
    if not sale:
        raise HTTPException(404, "Venta no encontrada")
    consecutivo = await _next_invoice_number()
    inv = await db.invoices.create(data={"venta_id": sale_id, "consecutivo": consecutivo, "impresa": False})
    return {"ok": True, "invoice_id": inv.id, "consecutivo": consecutivo}
