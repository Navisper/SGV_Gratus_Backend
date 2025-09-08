from fastapi import FastAPI
from db.client import db, connect_db, disconnect_db
from routers import products, sales, invoices, reports

app = FastAPI(title="Sistema de Ventas")

@app.on_event("startup")
async def startup():
    await connect_db()

@app.on_event("shutdown")
async def shutdown():
    await disconnect_db()

# Routers
app.include_router(products.router, prefix="/products", tags=["Productos"])
app.include_router(sales.router, prefix="/sales", tags=["Ventas"])
app.include_router(invoices.router, prefix="/invoices", tags=["Facturas"])
app.include_router(reports.router, prefix="/reports", tags=["Reportes"])
