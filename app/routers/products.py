from fastapi import APIRouter, Depends, HTTPException
from app.db.client import db
from app.core.security import require_role

router = APIRouter()

#metodo productos
@router.get(
    "/",
    summary="Listar productos",
    description="Obtiene una lista paginada de todos los productos en el sistema ordenados por fecha de creación descendente",
    response_description="Lista de productos con sus detalles"
)
async def list_products(
    skip: int = 0, 
    take: int = 100, 
    _=Depends(require_role("admin","cajero"))
):
    """
    Obtiene una lista de productos con paginación.
    
    Args:
        skip (int): Número de productos a omitir (para paginación)
        take (int): Número máximo de productos a retornar (límite de página)
        _: Dependencia de autenticación para roles admin o cajero
    
    Returns:
        list: Lista de objetos producto con todos sus campos
    
    Raises:
        HTTPException: Si el usuario no tiene permisos suficientes
    """
    return await db.products.find_many(skip=skip, take=take, order={"created_at": "desc"})

@router.get(
    "/{codigo_unico}",
    summary="Obtener producto por código único",
    description="Busca y retorna un producto específico utilizando su código único identificador",
    response_description="Detalles completos del producto encontrado"
)
async def get_by_code(
    codigo_unico: str, 
    _=Depends(require_role("admin","cajero"))
):
    """
    Obtiene un producto específico por su código único.
    
    Args:
        codigo_unico (str): Código único identificador del producto
        _: Dependencia de autenticación para roles admin o cajero
    
    Returns:
        dict: Objeto producto con todos sus campos
    
    Raises:
        HTTPException: 404 - Si no se encuentra el producto
        HTTPException: Si el usuario no tiene permisos suficientes
    """
    prod = await db.products.find_unique(where={"codigo_unico": codigo_unico})
    if not prod:
        raise HTTPException(404, "Producto no encontrado")
    return prod

@router.post(
    "/",
    summary="Crear nuevo producto",
    description="Crea un nuevo producto en el sistema con los datos proporcionados",
    response_description="Detalles del producto creado"
)
async def create_product(
    data: dict, 
    _=Depends(require_role("admin","cajero"))
):
    """
    Crea un nuevo producto en la base de datos.
    
    Args:
        data (dict): Diccionario con los datos del producto a crear.
                    Debe incluir campos como: nombre, descripción, precio, etc.
        _: Dependencia de autenticación para roles admin o cajero
    
    Returns:
        dict: Objeto producto creado con todos sus campos
    
    Raises:
        HTTPException: Si el usuario no tiene permisos suficientes
        HTTPException: Si hay errores de validación en los datos
    """
    return await db.products.create(data=data)

@router.put(
    "/{codigo_unico}",
    summary="Actualizar producto",
    description="Actualiza un producto existente identificado por su código único",
    response_description="Detalles del producto actualizado"
)
async def update_product(
    codigo_unico: str, 
    data: dict, 
    _=Depends(require_role("admin","cajero"))
):
    """
    Actualiza un producto existente.
    
    Args:
        codigo_unico (str): Código único identificador del producto a actualizar
        data (dict): Diccionario con los campos a actualizar y sus nuevos valores
        _: Dependencia de autenticación para roles admin o cajero
    
    Returns:
        dict: Objeto producto actualizado con todos sus campos
    
    Raises:
        HTTPException: Si el usuario no tiene permisos suficientes
        HTTPException: Si el producto no existe
    """
    return await db.products.update(where={"codigo_unico": codigo_unico}, data=data)

@router.delete(
    "/{codigo_unico}",
    summary="Eliminar producto",
    description="Elimina permanentemente un producto del sistema usando su código único",
    response_description="Detalles del producto eliminado"
)
async def delete_product(
    codigo_unico: str, 
    _=Depends(require_role("admin","cajero"))
):
    """
    Elimina un producto del sistema.
    
    Args:
        codigo_unico (str): Código único identificador del producto a eliminar
        _: Dependencia de autenticación para roles admin o cajero
    
    Returns:
        dict: Objeto producto eliminado con todos sus campos
    
    Raises:
        HTTPException: Si el usuario no tiene permisos suficientes
        HTTPException: Si el producto no existe
    """
    return await db.products.delete(where={"codigo_unico": codigo_unico})