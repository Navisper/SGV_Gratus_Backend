from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

# ---------------------------
# Pydantic Schemas
# ---------------------------

class CustomerIn(BaseModel):
    """Esquema para creación y actualización de clientes"""
    nombre: str = Field(..., min_length=1, max_length=200, description="Nombre completo del cliente")
    telefono: Optional[str] = Field(None, max_length=20, description="Número de teléfono del cliente")
    email: Optional[EmailStr] = Field(None, description="Email válido del cliente")
    direccion: Optional[str] = Field(None, max_length=500, description="Dirección física del cliente")

class CustomerResponse(BaseModel):
    """Esquema de respuesta para datos del cliente"""
    id: str
    nombre: str
    telefono: Optional[str]
    email: Optional[str]
    direccion: Optional[str]
    created_at: str
    updated_at: str

class CustomerListResponse(BaseModel):
    """Esquema para respuesta de lista de clientes"""
    customers: List[CustomerResponse]
    total: int
    skip: int
    take: int

# ---------------------------
# Endpoints
# ---------------------------

@router.post(
    "/",
    response_model=CustomerResponse,
    status_code=201,
    summary="Crear nuevo cliente",
    description="Crea un nuevo cliente en el sistema con la información básica proporcionada",
    response_description="Detalles del cliente creado",
    responses={
        201: {"description": "Cliente creado exitosamente"},
        400: {"description": "Datos de entrada inválidos"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def create_customer(body: CustomerIn):
    """
    Crea un nuevo cliente en la base de datos.
    
    Args:
        body (CustomerIn): Datos del cliente a crear incluyendo:
            - nombre (obligatorio): Nombre completo del cliente
            - telefono (opcional): Número de teléfono
            - email (opcional): Dirección de email válida
            - direccion (opcional): Dirección física
    
    Returns:
        CustomerResponse: Cliente creado con todos sus datos incluyendo ID y timestamps
    
    Raises:
        HTTPException: 400 - Si los datos de entrada son inválidos
        HTTPException: 403 - Si el usuario no tiene permisos suficientes
    """
    return await db.customers.create(data=body.dict())


@router.get(
    "/",
    response_model=List[CustomerResponse],
    summary="Listar clientes",
    description="Obtiene una lista paginada de clientes con posibilidad de búsqueda por nombre, email o teléfono",
    response_description="Lista de clientes que coinciden con los criterios",
    responses={
        200: {"description": "Lista de clientes obtenida exitosamente"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def list_customers(
    q: Optional[str] = Query(
        None, 
        description="Término de búsqueda para filtrar por nombre, email o teléfono (búsqueda case-insensitive)"
    ),
    take: int = Query(
        50, 
        ge=1, 
        le=200, 
        description="Número máximo de clientes a retornar (límite de página, 1-200)"
    ),
    skip: int = Query(
        0, 
        ge=0, 
        description="Número de clientes a omitir (para paginación)"
    )
):
    """
    Obtiene una lista de clientes con opciones de búsqueda y paginación.
    
    Permite:
    - Búsqueda textual en nombre, email y teléfono
    - Paginación mediante skip y take
    - Ordenamiento por fecha de creación descendente
    
    Args:
        q (str, optional): Término de búsqueda para filtrar clientes. 
                          Busca en los campos: nombre, email y teléfono.
        take (int): Número máximo de clientes a retornar (default: 50, max: 200)
        skip (int): Número de clientes a omitir para paginación (default: 0)
    
    Returns:
        List[CustomerResponse]: Lista de clientes que coinciden con los criterios
    
    Examples:
        - GET /customers/ → Todos los clientes (primeros 50)
        - GET /customers/?q=maria → Clientes que contengan "maria" en nombre, email o teléfono
        - GET /customers/?take=20&skip=10 → Clientes del 11 al 30
        - GET /customers/?q=juan&take=10&skip=0 → Primeros 10 clientes que contengan "juan"
    """
    if q:
        # Búsqueda en múltiples campos
        return await db.customers.find_many(
            where={
                "OR": [
                    {"nombre": {"contains": q, "mode": "insensitive"}},
                    {"email": {"contains": q, "mode": "insensitive"}},
                    {"telefono": {"contains": q, "mode": "insensitive"}},
                ]
            },
            take=take, 
            skip=skip, 
            order={"created_at": "desc"}
        )
    
    # Lista simple sin filtros de búsqueda
    return await db.customers.find_many(
        take=take, 
        skip=skip, 
        order={"created_at": "desc"}
    )

# Agregar al archivo customers.py si necesitas estas funcionalidades

@router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Obtener cliente por ID",
    description="Obtiene los detalles completos de un cliente específico usando su ID único",
    response_description="Detalles completos del cliente",
    responses={
        200: {"description": "Cliente encontrado"},
        404: {"description": "Cliente no encontrado"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def get_customer(customer_id: str):
    """
    Obtiene un cliente específico por su ID único.
    
    Args:
        customer_id (str): ID único del cliente
    
    Returns:
        CustomerResponse: Cliente con todos sus datos
    
    Raises:
        HTTPException: 404 - Si no se encuentra el cliente
    """
    customer = await db.customers.find_unique(where={"id": customer_id})
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return customer


@router.put(
    "/{customer_id}",
    response_model=CustomerResponse,
    summary="Actualizar cliente",
    description="Actualiza la información de un cliente existente usando su ID único",
    response_description="Detalles del cliente actualizado",
    responses={
        200: {"description": "Cliente actualizado exitosamente"},
        404: {"description": "Cliente no encontrado"},
        400: {"description": "Datos de entrada inválidos"},
        403: {"description": "No autorizado - se requieren roles admin o cajero"}
    },
    dependencies=[Depends(require_role("admin","cajero"))]
)
async def update_customer(customer_id: str, body: CustomerIn):
    """
    Actualiza un cliente existente.
    
    Args:
        customer_id (str): ID único del cliente a actualizar
        body (CustomerIn): Datos actualizados del cliente
    
    Returns:
        CustomerResponse: Cliente actualizado con todos sus datos
    
    Raises:
        HTTPException: 404 - Si no se encuentra el cliente
    """
    # Verificar que el cliente existe
    existing_customer = await db.customers.find_unique(where={"id": customer_id})
    if not existing_customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    return await db.customers.update(
        where={"id": customer_id}, 
        data=body.dict(exclude_unset=True)
    )


@router.delete(
    "/{customer_id}",
    status_code=204,
    summary="Eliminar cliente",
    description="Elimina permanentemente un cliente del sistema usando su ID único",
    responses={
        204: {"description": "Cliente eliminado exitosamente"},
        404: {"description": "Cliente no encontrado"},
        403: {"description": "No autorizado - se requiere rol admin"}
    },
    dependencies=[Depends(require_role("admin"))]
)
async def delete_customer(customer_id: str):
    """
    Elimina un cliente del sistema.
    
    Args:
        customer_id (str): ID único del cliente a eliminar
    
    Raises:
        HTTPException: 404 - Si no se encuentra el cliente
        HTTPException: 403 - Si el usuario no tiene rol de admin
    """
    # Verificar que el cliente existe
    existing_customer = await db.customers.find_unique(where={"id": customer_id})
    if not existing_customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    await db.customers.delete(where={"id": customer_id})
    # FastAPI automáticamente retornará 204 No Content