# Usar la imagen oficial de Playwright con Python
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Establecer directorio de trabajo
WORKDIR /app

# Copiar archivos de dependencias
COPY requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY main.py .

# Exponer el puerto
EXPOSE 8080

# Variables de entorno
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Comando de inicio con timeout de 300 segundos (5 minutos)
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080", "--timeout", "300", "--workers", "1", "--log-level", "debug"]