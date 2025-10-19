from fastapi import FastAPI
from app.db.client import connect_db, disconnect_db
from app.routers import products, sales, invoices, reports, auth

app = FastAPI(title="Gratus - Sistema de Gestión de Ventas")

@app.on_event("startup")
async def startup():
    await connect_db()

@app.on_event("shutdown")
async def shutdown():
    await disconnect_db()

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(products.router, prefix="/products", tags=["Productos"])
app.include_router(sales.router, prefix="/sales", tags=["Ventas"])
app.include_router(invoices.router, prefix="/invoices", tags=["Facturas"])
app.include_router(reports.router, prefix="/reports", tags=["Reportes"])
