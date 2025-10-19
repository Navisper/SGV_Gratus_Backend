from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

@router.post("/")
async def create_sale(payload: Dict[str, Any], _=Depends(require_role("admin","cajero"))):
    items = payload.pop("items", [])
    if not items:
        raise HTTPException(400, "Debe incluir items de venta")
    codes = [i["codigo_unico"] for i in items]
    prods = await db.products.find_many(where={"codigo_unico": {"in": codes}})
    pmap = {p.codigo_unico: p for p in prods}
    for it in items:
        p = pmap.get(it["codigo_unico"])
        if not p or (p.stock or 0) < it["cantidad"]:
            raise HTTPException(400, f"Stock insuficiente o producto no existe: {it['codigo_unico']}")
    subtotal = sum(it["precio_unitario"] * it["cantidad"] for it in items)
    total = subtotal - float(payload.get("descuento",0) or 0)
    payload["total"] = total
    async with db.tx() as tx:
        sale = await tx.sales.create(data={**payload})
        for it in items:
            p = pmap[it["codigo_unico"]]
            await tx.sale_items.create(data={
                "venta_id": sale.id,
                "producto_id": p.id,
                "cantidad": it["cantidad"],
                "precio_unitario": it["precio_unitario"],
                "subtotal": it["precio_unitario"] * it["cantidad"]
            })
            await tx.products.update(where={"id": p.id}, data={"stock": (p.stock - it["cantidad"])})
    return {"ok": True, "sale_id": sale.id, "total": total}
