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

#metodo para ventas

class SaleItemIn(BaseModel):
    """Esquema para items individuales de una venta"""
    codigo_unico: str = Field(..., min_length=1, description="Código único del producto")
    cantidad: int = Field(..., gt=0, description="Cantidad vendida (mayor a 0)")
    precio_unitario: float = Field(..., gt=0, description="Precio unitario al momento de la venta")

class SaleCreate(BaseModel):
    """Esquema para creación de una nueva venta"""
    usuario_id: Optional[str] = Field(None, description="ID del usuario que realiza la venta")
    tienda_id: Optional[str] = Field(None, description="ID de la tienda donde se realiza la venta")
    metodo_pago: str = Field(..., min_length=1, description="Método de pago: efectivo|tarjeta|transferencia|etc")
    descuento: float = Field(0, ge=0, description="Descuento total aplicado a la venta")
    items: List[SaleItemIn] = Field(..., description="Lista de items vendidos")

    @validator("items")
    def validate_items(cls, v):
        """Valida que la venta tenga al menos un item"""
        if not v or len(v) == 0:
            raise ValueError("Debe incluir items de venta")
        return v

# ---------------------------
# Response Schemas
# ---------------------------

class SaleItemResponse(BaseModel):
    """Esquema de respuesta para items de venta"""
    id: str
    producto_id: str
    codigo_unico: str
    nombre: str
    cantidad: int
    precio_unitario: float
    subtotal: float

class SaleResponse(BaseModel):
    """Esquema de respuesta para venta completa"""
    id: str
    usuario_id: Optional[str]
    tienda_id: Optional[str]
    metodo_pago: str
    descuento: float
    total: float
    created_at: datetime
    anulada: bool
    items: List[SaleItemResponse]

class SaleCreateResponse(BaseModel):
    """Esquema de respuesta para creación de venta"""
    ok: bool
    sale_id: str
    subtotal: float
    descuento: float
    total: float

class KPIDailyResponse(BaseModel):
    """Esquema de respuesta para KPIs diarios"""
    day: str
    head: Dict[str, Any]
    by_method: List[Dict[str, Any]]
    top_products: List[Dict[str, Any]]

class CloseDayResponse(BaseModel):
    """Esquema de respuesta para cierre de día"""
    day: str
    summary: Dict[str, Any]
    by_method: List[Dict[str, Any]]
    items: List[Dict[str, Any]]

class CancelSaleResponse(BaseModel):
    """Esquema de respuesta para cancelación de venta"""
    ok: bool
    sale_id: str
    message: str

# ---------------------------
# Helpers
# ---------------------------

def _parse_date(s: Optional[str]) -> Optional[date]:
    """Convierte string en formato YYYY-MM-DD a objeto date"""
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()

# ---------------------------
# Endpoints
# ---------------------------

@router.post(
    "/",
    response_model=SaleCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear nueva venta",
    description="Crea una nueva venta en el sistema con validación de stock y actualización de inventario",
    response_description="Detalles de la venta creada incluyendo ID y totales",
    responses={
        201: {"description": "Venta creada exitosamente"},
        400: {"description": "Datos inválidos, producto no existe o stock insuficiente"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def create_sale(payload: SaleCreate):
    """
    Crea una nueva venta en el sistema.
    
    Realiza las siguientes operaciones:
    - Valida la existencia de todos los productos
    - Verifica stock suficiente para cada item
    - Calcula subtotal, descuentos y total
    - Crea registro de venta y items
    - Actualiza stock de productos
    
    Args:
        payload (SaleCreate): Datos de la venta incluyendo items, método de pago y descuentos
    
    Returns:
        SaleCreateResponse: Confirmación de venta creada con ID y totales
    
    Raises:
        HTTPException: 400 - Si algún producto no existe o no hay stock suficiente
        HTTPException: 403 - Si el usuario no tiene permisos suficientes
    """
    codes = [i.codigo_unico for i in payload.items]
    prods = await db.products.find_many(where={"codigo_unico": {"in": codes}})
    pmap = {p.codigo_unico: p for p in prods}

    # Validar productos y stock
    for it in payload.items:
        p = pmap.get(it.codigo_unico)
        if not p:
            raise HTTPException(400, f"Producto no existe: {it.codigo_unico}")
        if (p.stock or 0) < it.cantidad:
            raise HTTPException(400, f"Stock insuficiente para {p.nombre} ({p.codigo_unico})")

    # Calcular totales
    subtotal = sum(it.precio_unitario * it.cantidad for it in payload.items)
    total = subtotal - float(payload.descuento or 0)
    if total < 0:
        raise HTTPException(400, "El total no puede ser negativo")

    # Preparar datos de venta
    sale_data: Dict[str, Any] = {
        "metodo_pago": payload.metodo_pago,
        "descuento": payload.descuento,
        "total": total,
    }
    # incluir solo si vienen
    if payload.usuario_id: sale_data["usuario_id"] = payload.usuario_id
    if payload.tienda_id:  sale_data["tienda_id"]  = payload.tienda_id

    # Transacción para crear venta y actualizar stock
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


@router.get(
    "/{sale_id}",
    response_model=SaleResponse,
    summary="Obtener venta por ID",
    description="Obtiene los detalles completos de una venta específica incluyendo todos sus items",
    response_description="Detalles completos de la venta con items",
    responses={
        200: {"description": "Venta encontrada"},
        400: {"description": "ID de venta inválido o mal formateado"},
        404: {"description": "Venta no encontrada"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"},
        500: {"description": "Error interno del servidor"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def get_sale(sale_id: str):
    """
    Obtiene una venta específica por su ID con todos sus items y datos de productos.
    
    Args:
        sale_id (str): ID único de la venta en formato UUID
    
    Returns:
        SaleResponse: Venta completa con items y detalles de productos
    
    Raises:
        HTTPException: 400 - Si el ID está vacío o tiene formato inválido
        HTTPException: 404 - Si no se encuentra la venta
        HTTPException: 500 - Error interno del servidor
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


@router.get(
    "/",
    summary="Listar ventas",
    description="Obtiene una lista paginada de ventas con filtros opcionales por fecha, tienda, usuario, etc.",
    response_description="Lista de ventas que cumplen con los criterios de filtro",
    responses={
        200: {"description": "Lista de ventas obtenida exitosamente"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def list_sales(
    date_from: Optional[str] = Query(None, description="Fecha inicial en formato YYYY-MM-DD"),
    date_to: Optional[str]   = Query(None, description="Fecha final en formato YYYY-MM-DD (inclusive)"),
    tienda_id: Optional[str] = Query(None, description="Filtrar por ID de tienda"),
    usuario_id: Optional[str] = Query(None, description="Filtrar por ID de usuario"),
    metodo_pago: Optional[str] = Query(None, description="Filtrar por método de pago"),
    anulada: Optional[bool] = Query(None, description="Filtrar por estado de anulación"),
    limit: int = Query(20, ge=1, le=200, description="Límite de resultados por página (1-200)"),
    offset: int = Query(0, ge=0, description="Número de resultados a omitir (para paginación)"),
):
    """
    Lista ventas con filtros avanzados y paginación.
    
    Permite filtrar por:
    - Rango de fechas
    - Tienda específica
    - Usuario específico
    - Método de pago
    - Estado de anulación
    
    Args:
        date_from (str, optional): Fecha inicial del rango
        date_to (str, optional): Fecha final del rango
        tienda_id (str, optional): ID de tienda para filtrar
        usuario_id (str, optional): ID de usuario para filtrar
        metodo_pago (str, optional): Método de pago para filtrar
        anulada (bool, optional): Estado de anulación para filtrar
        limit (int): Límite de resultados por página (default: 20)
        offset (int): Offset para paginación (default: 0)
    
    Returns:
        list: Lista de ventas que cumplen con los criterios de filtro
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


@router.get(
    "/kpi/daily",
    response_model=KPIDailyResponse,
    summary="KPIs diarios de ventas",
    description="Obtiene indicadores clave de desempeño para un día específico: número de ventas, total vendido, distribución por método de pago y productos más vendidos",
    response_description="Métricas de ventas del día solicitado",
    responses={
        200: {"description": "KPIs del día obtenidos exitosamente"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def kpi_daily(day: Optional[str] = Query(None, description="Fecha en formato YYYY-MM-DD; por defecto hoy")):
    """
    Obtiene KPIs del día específico.
    
    Métricas incluidas:
    - Número total de ventas
    - Total vendido
    - Distribución por método de pago
    - Top 5 productos más vendidos
    
    Args:
        day (str, optional): Fecha en formato YYYY-MM-DD. Si no se especifica, usa la fecha actual
    
    Returns:
        KPIDailyResponse: Objeto con todas las métricas del día
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


@router.get(
    "/close/day",
    response_model=CloseDayResponse,
    summary="Cierre de día",
    description="Genera un resumen completo de cierre de día incluyendo ventas, totales, métodos de pago y detalle de productos vendidos",
    response_description="Resumen completo de cierre de día",
    responses={
        200: {"description": "Resumen de cierre generado exitosamente"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def close_day(day: Optional[str] = Query(None, description="Fecha en formato YYYY-MM-DD; por defecto hoy")):
    """
    Genera resumen de cierre de día.
    
    Incluye:
    - Número de ventas, total vendido y descuentos aplicados
    - Desglose por método de pago
    - Detalle de productos vendidos con cantidades y totales
    
    Args:
        day (str, optional): Fecha en formato YYYY-MM-DD. Si no se especifica, usa la fecha actual
    
    Returns:
        CloseDayResponse: Resumen completo del día
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


@router.post(
    "/{sale_id}/cancel",
    response_model=CancelSaleResponse,
    summary="Cancelar venta",
    description="Anula una venta existente, restaura el stock de productos y marca la venta como anulada",
    response_description="Confirmación de cancelación de venta",
    responses={
        200: {"description": "Venta cancelada exitosamente"},
        400: {"description": "ID de venta inválido o venta sin items"},
        404: {"description": "Venta no encontrada"},
        409: {"description": "La venta ya está anulada"},
        403: {"description": "No autorizado - se requiere rol admin"}
    },
    dependencies=[Depends(require_role("admin"))]
)
async def cancel_sale(sale_id: str):
    """
    Anula una venta existente.
    
    Proceso de cancelación:
    - Valida que la venta existe y no está ya anulada
    - Restaura el stock de todos los productos de la venta
    - Marca la venta como anulada
    
    Args:
        sale_id (str): ID único de la venta en formato UUID
    
    Returns:
        CancelSaleResponse: Confirmación de cancelación exitosa
    
    Raises:
        HTTPException: 400 - Si el ID es inválido o la venta no tiene items
        HTTPException: 404 - Si no se encuentra la venta
        HTTPException: 409 - Si la venta ya está anulada
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
