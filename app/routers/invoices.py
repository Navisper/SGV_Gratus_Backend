from fastapi import APIRouter, HTTPException, Depends, Query, status
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

# ---------------------------
# Pydantic Schemas
# ---------------------------


#metodo factura

class InvoiceGenerateResponse(BaseModel):
    """Esquema de respuesta para generación de factura"""
    ok: bool = Field(..., description="Indica si la operación fue exitosa")
    invoice_id: str = Field(..., description="ID único de la factura generada")
    consecutivo: int = Field(..., description="Número consecutivo asignado a la factura")

class InvoiceResponse(BaseModel):
    """Esquema de respuesta para datos de factura"""
    id: str
    venta_id: str
    consecutivo: int
    impresa: bool
    created_at: str
    updated_at: str

# ---------------------------
# Helper Functions
# ---------------------------

async def _next_invoice_number() -> int:
    """
    Obtiene el siguiente número consecutivo para facturas.
    
    Realiza una consulta a la base de datos para obtener el máximo número consecutivo
    actual y retorna el siguiente número disponible.
    
    Returns:
        int: Siguiente número consecutivo disponible para facturación
    
    Example:
        >>> await _next_invoice_number()
        1001
    """
    row = await db.query_first("SELECT COALESCE(MAX(consecutivo),0)+1 AS next FROM invoices")  # type: ignore
    return int(row["next"]) if row and "next" in row else 1

# ---------------------------
# Endpoints
# ---------------------------

@router.post(
    "/{sale_id}",
    response_model=InvoiceGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generar factura para venta",
    description="Genera una nueva factura para una venta existente, asignando un número consecutivo automático",
    response_description="Detalles de la factura generada incluyendo ID y número consecutivo",
    responses={
        201: {"description": "Factura generada exitosamente"},
        404: {"description": "Venta no encontrada"},
        403: {"description": "No autorizado - se requiere rol admin"},
        500: {"description": "Error interno del servidor al generar factura"}
    }
)
async def generate_invoice(sale_id: str, _=Depends(require_role("admin"))):
    """
    Genera una factura para una venta existente.
    
    Proceso de generación:
    1. Valida que la venta existe y obtiene sus detalles
    2. Obtiene el siguiente número consecutivo disponible
    3. Crea el registro de factura en la base de datos
    4. Retorna los detalles de la factura generada
    
    Args:
        sale_id (str): ID único de la venta para la cual generar la factura
        _: Dependencia de autenticación que requiere rol de administrador
    
    Returns:
        InvoiceGenerateResponse: Confirmación de factura generada con ID y número consecutivo
    
    Raises:
        HTTPException: 404 - Si no se encuentra la venta especificada
        HTTPException: 403 - Si el usuario no tiene rol de administrador
        HTTPException: 500 - Si ocurre un error al generar el número consecutivo
    
    Example:
        POST /invoices/123e4567-e89b-12d3-a456-426614174000
        Response: {
            "ok": true,
            "invoice_id": "123e4567-e89b-12d3-a456-426614174001",
            "consecutivo": 1001
        }
    """
    # Validar que la venta existe y obtener sus items
    sale = await db.sales.find_unique(where={"id": sale_id}, include={"items": True})
    if not sale:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Venta no encontrada"
        )
    
    try:
        # Obtener siguiente número consecutivo
        consecutivo = await _next_invoice_number()
        
        # Crear registro de factura
        inv = await db.invoices.create(data={
            "venta_id": sale_id, 
            "consecutivo": consecutivo, 
            "impresa": False
        })
        
        return {
            "ok": True, 
            "invoice_id": inv.id, 
            "consecutivo": consecutivo
        }
        
    except Exception as e:
        # Log del error para debugging
        print(f"Error al generar factura: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor al generar la factura"
        )

# Agregar al archivo invoices.py si necesitas estas funcionalidades

@router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    summary="Obtener factura por ID",
    description="Obtiene los detalles completos de una factura específica usando su ID único",
    response_description="Detalles completos de la factura",
    responses={
        200: {"description": "Factura encontrada"},
        404: {"description": "Factura no encontrada"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def get_invoice(invoice_id: str):
    """
    Obtiene una factura específica por su ID único.
    
    Args:
        invoice_id (str): ID único de la factura
    
    Returns:
        InvoiceResponse: Factura con todos sus datos
    
    Raises:
        HTTPException: 404 - Si no se encuentra la factura
    """
    invoice = await db.invoices.find_unique(where={"id": invoice_id})
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Factura no encontrada"
        )
    return invoice


@router.get(
    "/sale/{sale_id}",
    response_model=InvoiceResponse,
    summary="Obtener factura por venta",
    description="Obtiene la factura asociada a una venta específica",
    response_description="Factura asociada a la venta",
    responses={
        200: {"description": "Factura encontrada"},
        404: {"description": "No existe factura para esta venta"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def get_invoice_by_sale(sale_id: str):
    """
    Obtiene la factura asociada a una venta específica.
    
    Args:
        sale_id (str): ID único de la venta
    
    Returns:
        InvoiceResponse: Factura asociada a la venta
    
    Raises:
        HTTPException: 404 - Si no existe factura para la venta especificada
    """
    invoice = await db.invoices.find_first(where={"venta_id": sale_id})
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="No existe factura para esta venta"
        )
    return invoice


@router.put(
    "/{invoice_id}/print",
    response_model=InvoiceResponse,
    summary="Marcar factura como impresa",
    description="Marca una factura como impresa, indicando que ha sido procesada físicamente",
    response_description="Factura actualizada con estado de impresa",
    responses={
        200: {"description": "Factura marcada como impresa exitosamente"},
        404: {"description": "Factura no encontrada"},
        403: {"description": "No autorizado - se requiere rol admin"}
    },
    dependencies=[Depends(require_role("admin"))]
)
async def mark_invoice_printed(invoice_id: str):
    """
    Marca una factura como impresa.
    
    Args:
        invoice_id (str): ID único de la factura a marcar como impresa
    
    Returns:
        InvoiceResponse: Factura actualizada con estado de impresa
    
    Raises:
        HTTPException: 404 - Si no se encuentra la factura
    """
    # Verificar que la factura existe
    existing_invoice = await db.invoices.find_unique(where={"id": invoice_id})
    if not existing_invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Factura no encontrada"
        )
    
    # Marcar como impresa
    return await db.invoices.update(
        where={"id": invoice_id}, 
        data={"impresa": True}
    )


@router.get(
    "/",
    response_model=List[InvoiceResponse],
    summary="Listar facturas",
    description="Obtiene una lista paginada de facturas con opciones de filtrado",
    response_description="Lista de facturas que cumplen con los criterios",
    responses={
        200: {"description": "Lista de facturas obtenida exitosamente"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin", "cajero"))]
)
async def list_invoices(
    skip: int = Query(0, ge=0, description="Número de facturas a omitir (para paginación)"),
    take: int = Query(50, ge=1, le=100, description="Número máximo de facturas a retornar (1-100)"),
    impresa: Optional[bool] = Query(None, description="Filtrar por estado de impresión")
):
    """
    Obtiene una lista de facturas con paginación y filtros opcionales.
    
    Args:
        skip (int): Número de facturas a omitir (default: 0)
        take (int): Número máximo de facturas a retornar (default: 50, max: 100)
        impresa (bool, optional): Filtrar por estado de impresión
    
    Returns:
        List[InvoiceResponse]: Lista de facturas que cumplen con los criterios
    """
    where_filter = {}
    if impresa is not None:
        where_filter["impresa"] = impresa
    
    return await db.invoices.find_many(
        where=where_filter,
        skip=skip,
        take=take,
        order={"created_at": "desc"}
    )