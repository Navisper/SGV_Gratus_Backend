# Gratus SGV — Backend (FastAPI)

> Estado actual: API en FastAPI con endpoints para productos, ventas y reportes. Conexion a PostgreSQL (async). Se han observado errores como `GET /sales/undefined` y consultas SQL para reportes.

## Descripcion
Servicio backend del sistema de ventas e inventario "Gratus". Expone endpoints REST para:
- CRUD de productos
- Registro de ventas y sus items
- Reportes (resumen global, top productos)
- Seguridad basica por roles (ej. require_role("admin"))

## Stack
- Python 3.11+
- FastAPI + Uvicorn
- Conector async a PostgreSQL (p. ej. asyncpg / wrapper de cliente)
- Autenticacion/autorizacion por dependencia (require_role)
- CORS habilitable para frontend

Nota: si usas Prisma Client Python u otro ORM, ajusta los comandos de migracion a tu flujo. Este README asume conexion a Postgres ya lista.

## Requisitos
- Python 3.11+
- PostgreSQL 14+ (local o remoto)
- (Opcional) Docker y Docker Compose

## TL;DR (arranque rapido)
```bash
# 1) Clona y entra
git clone <repo-backend-url> gratus-sgv-backend
cd gratus-sgv-backend

# 2) Crea y activa venv
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 3) Instala dependencias
pip install -r requirements.txt

# 4) Variables de entorno
cp .env.example .env
# Edita DATABASE_URL, CORS_ORIGINS, JWT_SECRET, etc.

# 5) Ejecuta en desarrollo
uvicorn app.main:app --reload --port 8000

# 6) Prueba
curl http://localhost:8000/health
```

## Variables de entorno
Archivo `.env` (ejemplo):
```ini
# Postgres (formato: postgresql+asyncpg://user:pass@host:5432/dbname)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gratus

# CORS: origen del frontend
CORS_ORIGINS=http://localhost:5173

# Seguridad (ajusta segun tu implementacion real)
JWT_SECRET=super-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Puerto uvicorn (si lo levantas via script propio)
PORT=8000
```

## Endpoints principales
Algunos nombres/paths pueden cambiar segun tu router. Ajusta si es necesario.

- `GET /health` -> ping de salud
- `GET /products` | `POST /products` | `PUT /products/{id}` | `DELETE /products/{id}`
  - Producto: `{ id, codigo_unico, nombre, precio?, costo?, stock? }`
- `POST /sales` -> crea venta con items
- `GET /sales/{id}` -> detalle de venta
- `GET /reports/summary` -> `{ num_productos, num_ventas, total_vendido }`
- `GET /reports/top-products?limit=10` -> lista con `codigo_unico, nombre, unidades, vendido`

### Ejemplo de reports.py
```py
@router.get("/summary")
async def summary(_=Depends(require_role("admin"))):
    q = ("SELECT (SELECT COUNT(*) FROM products) AS num_productos, "
         "(SELECT COUNT(*) FROM sales) AS num_ventas, "
         "(SELECT COALESCE(SUM(total),0) FROM sales) AS total_vendido")
    row = await db.query_first(q)
    return row
```

## Estructura tipica
```
app/
  main.py            # crea FastAPI(), incluye routers, CORS, etc.
  core/
    config.py
    security.py      # require_role(...)
  db/
    client.py        # inicializacion de conexion async
    migrations/      # si gestionas migraciones
  routers/
    products.py
    sales.py
    reports.py
  models/            # Pydantic/ORM
  schemas/           # Pydantic
tests/
```

## Comandos utiles
```bash
# Desarrollo
uvicorn app.main:app --reload --port 8000

# Produccion (ejemplo simple)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Formateo / lint
ruff check .        # si usas ruff
black .             # si usas black
pytest -q           # si tienes tests
```

## CORS
Asegurate de permitir el origen del frontend (por defecto `http://localhost:5173`):
```py
from fastapi.middleware.cors import CORSMiddleware
import os

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGINS", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Troubleshooting (segun casos reales)
- `GET /sales/undefined` devuelve 500  
  El front esta llamando a `/sales/undefined`. Revisa el ID que envias desde el frontend (state/param). En el backend anade validacion para `id`:
  ```py
  from fastapi import Path

  @router.get("/sales/{sale_id}")
  async def get_sale(sale_id: int = Path(..., gt=0)):
      # 422 si no es int valido, 404 si no existe
      ...
  ```

- Errores con reportes y SQL  
  Usa `COALESCE` cuando sumes campos opcionales. Ejemplo (top productos):
  ```sql
  SELECT p.codigo_unico, p.nombre,
         SUM(si.cantidad) AS unidades,
         SUM(si.subtotal) AS vendido
  FROM sale_items si
  JOIN products p ON p.id = si.product_id
  GROUP BY p.codigo_unico, p.nombre
  ORDER BY vendido DESC
  LIMIT $1;
  ```

- Conexion a Postgres (async)  
  Verifica que `DATABASE_URL` use el driver `+asyncpg`. Si usas otro cliente, ajusta el esquema.

- CORS bloquea peticiones del front  
  Habilita `allow_origins` para el dominio del frontend (incluye puerto y protocolo).

## Pruebas manuales
```bash
# Resumen
curl -H "Authorization: Bearer <token>" http://localhost:8000/reports/summary

# Top productos
curl http://localhost:8000/reports/top-products?limit=5
```

## Opcion Docker Compose (ejemplo)
Archivo `docker-compose.yml` (adaptar a tu repo real):
```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: gratus
    ports: ["5432:5432"]
    volumes: [db_data:/var/lib/postgresql/data]

  api:
    build: .
    env_file: .env
    ports: ["8000:8000"]
    depends_on: [db]
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

volumes:
  db_data:
```

## Checklist antes de produccion
- [ ] Variables `.env` seguras y rotadas
- [ ] Migraciones ejecutadas y BD en buen estado
- [ ] CORS configurado para dominios reales
- [ ] Logs y metricas habilitados
- [ ] Backups de BD
- [ ] Tests basicos en CI

## Licencia
MIT (o la que definas).

## Autores
- Julian Rubiano Santofimio (@DuelDEV-s / "Gratus") y colaboradores.
