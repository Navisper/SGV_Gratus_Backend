from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.client import connect_db, disconnect_db
from app.routers import products, sales, invoices, reports, auth, customers, credits
import os

app = FastAPI(title="Gratus - Sistema de Gestión de Ventas")

# --- CORS ---
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# -------------

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
app.include_router(customers.router, prefix="/customers", tags=["Clientes"])
app.include_router(credits.router, prefix="/credits", tags=["Créditos"])

