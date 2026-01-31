from flask import Flask, request, jsonify, send_file
from playwright.sync_api import sync_playwright
import os
import zipfile
import time

app = Flask(__name__)

# Ruta donde se guardarán los archivos temporales
TEMP_DIR = "/tmp/descargas"

# Función para descargar el pliego
def descargar_pliego(licitacion_id, url_detalle):
    """
    Esta función:
    1. Abre un navegador invisible
    2. Va a la URL de la licitación
    3. Descarga el ZIP
    4. Busca el archivo "pliego"
    5. Lo devuelve
    """
    
    # Crear carpeta temporal si no existe
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    with sync_playwright() as p:
        # Abrir navegador Chrome invisible
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # Ir a la página de la licitación
            page.goto(url_detalle, timeout=30000)
            
            # Esperar que cargue la página
            page.wait_for_timeout(2000)
            
            # Buscar el botón "Descargar procedimiento"
            # (Aquí ajustaremos el selector según el HTML real)
            descarga_button = page.locator('text="Descargar procedimiento"')
            
            # Configurar la descarga
            with page.expect_download() as download_info:
                descarga_button.click()
            
            download = download_info.value
            
            # Guardar el ZIP
            zip_path = f"{TEMP_DIR}/{licitacion_id}.zip"
            download.save_as(zip_path)
            
            # Descomprimir
            extract_path = f"{TEMP_DIR}/{licitacion_id}"
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            
            # Buscar el archivo "pliego"
            pliego_path = None
            adjuntos_path = f"{extract_path}/1_Publicaciones/Adjuntos"
            
            if os.path.exists(adjuntos_path):
                for file in os.listdir(adjuntos_path):
                    if "pliego" in file.lower():
                        pliego_path = os.path.join(adjuntos_path, file)
                        break
            
            browser.close()
            
            return pliego_path
            
        except Exception as e:
            browser.close()
            raise Exception(f"Error al descargar: {str(e)}")

# Endpoint principal
@app.route('/descargar-pliego', methods=['POST'])
def descargar_pliego_endpoint():
    """
    Este endpoint recibe:
    - licitacion_id: El ID de la licitación
    - url_detalle: La URL del detalle en el portal SECP
    
    Y devuelve el archivo pliego
    """
    
    data = request.json
    licitacion_id = data.get('licitacion_id')
    url_detalle = data.get('url_detalle')
    
    if not licitacion_id or not url_detalle:
        return jsonify({"error": "Faltan parámetros"}), 400
    
    try:
        pliego_path = descargar_pliego(licitacion_id, url_detalle)
        
        if pliego_path and os.path.exists(pliego_path):
            return send_file(pliego_path, as_attachment=True)
        else:
            return jsonify({"error": "No se encontró el pliego"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ruta de prueba
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "compita-descarga-pliegos"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)