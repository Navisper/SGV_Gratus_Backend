FROM python:3.11-slim

# Instalar uv
RUN pip install --no-cache-dir uv

# Crear directorio de trabajo
WORKDIR /app

# Copiar el pyproject
COPY pyproject.toml .

# Compilar dependencias desde pyproject.toml
RUN uv pip compile pyproject.toml > requirements.txt

# Instalar dependencias
RUN uv pip install --system --no-cache -r requirements.txt

# Copiar el resto del proyecto
COPY . .

# Exponer el puerto
EXPOSE 8000

# Ejecutar uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
