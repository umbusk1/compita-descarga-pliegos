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

# Variable de entorno para el puerto
ENV PORT=8080

# Comando de inicio
CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:8080"]