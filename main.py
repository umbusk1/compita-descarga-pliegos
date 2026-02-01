from flask import Flask, request, jsonify, send_file
from playwright.sync_api import sync_playwright
import os
import zipfile
import time
import re

app = Flask(__name__)

# Ruta donde se guardarán los archivos temporales
TEMP_DIR = "/tmp/descargas"

def descargar_pliego(referencia):
    """
    Esta función:
    1. Va al portal SECP
    2. Usa el buscador para encontrar la licitación
    3. Hace clic en DETALLE
    4. Hace clic en Descargar procedimiento
    5. Extrae el pliego del ZIP
    """
    
    # Crear carpeta temporal si no existe
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Limpiar nombre de archivo (quitar caracteres especiales)
    nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
    
    with sync_playwright() as p:
        # Abrir navegador Chrome invisible
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.set_default_timeout(120000)  # 2 minutos para todas las operaciones
        page = context.new_page()
        
        try:
            print(f"🔍 Buscando licitación: {referencia}")
            
            # 1. Ir a la página del listado
            url_listado = "https://comunidad.comprasdominicana.gob.do/Public/Tendering/ContractNoticeManagement/Index"
            page.goto(url_listado, timeout=90000)
            page.wait_for_timeout(5000)
            
            print(f"📋 Usando el buscador del portal...")
            
            # 2. Encontrar el campo de búsqueda
            # El campo está bajo el texto "Buscar Proceso de Compra"
            campo_busqueda = page.locator('input[type="text"]').first
            campo_busqueda.wait_for(state='visible', timeout=10000)
            
            # 3. Escribir la referencia en el campo
            campo_busqueda.fill(referencia)
            print(f"✍️ Referencia ingresada: {referencia}")
            
            # Esperar un poco después de escribir
            page.wait_for_timeout(1000)
            
            # 4. Hacer clic en el botón "Buscar"
            # Ser más específico: buscar el botón cerca del input
            print(f"🔎 Buscando el botón Buscar...")
            boton_buscar = page.get_by_role("button", name="Buscar").first
            boton_buscar.wait_for(state='visible', timeout=10000)
            print(f"✅ Botón Buscar encontrado")
            
            boton_buscar.click()
            print(f"✅ Clic en Buscar realizado")
            
            print(f"⏳ Esperando resultados de búsqueda...")
            
            # 5. Esperar a que se actualice la tabla (dar tiempo para que cargue)
            page.wait_for_timeout(5000)
            
            # 6. Verificar que hay resultados
            # Buscar la referencia en la tabla filtrada
            print(f"🔍 Buscando {referencia} en los resultados...")
            resultado = page.locator(f'text="{referencia}"').first
            
            if not resultado.is_visible(timeout=15000):
                raise Exception(f"No se encontró la licitación {referencia} después de buscar")
            
            print(f"✅ Licitación encontrada en resultados")
            
            # 7. Hacer clic en el botón DETALLE
            # El botón DETALLE está en la misma fila que la referencia
            print(f"🔍 Buscando botón DETALLE...")
            fila = resultado.locator('xpath=ancestor::tr')
            boton_detalle = fila.locator('button:has-text("DETALLE")').first
            
            print(f"🖱️ Haciendo clic en DETALLE...")
            boton_detalle.click()
            
            # 8. Esperar a que se abra el modal
            print(f"⏳ Esperando modal...")
            page.wait_for_timeout(3000)
            
            # Verificar que el modal está visible
            modal = page.locator('.modal-content, .modal-dialog').first
            modal.wait_for(state='visible', timeout=15000)
            
            print(f"✅ Modal abierto")
            
            # 9. Hacer clic en "Descargar procedimiento"
            print(f"⬇️ Descargando procedimiento...")
            
            # Configurar la descarga
            with page.expect_download(timeout=90000) as download_info:
                boton_descargar = page.locator('button:has-text("Descargar procedimiento")').first
                boton_descargar.click()
            
            download = download_info.value
            
            # 10. Guardar el ZIP
            zip_path = f"{TEMP_DIR}/{nombre_seguro}.zip"
            download.save_as(zip_path)
            
            print(f"💾 ZIP descargado: {zip_path}")
            
            # 11. Descomprimir
            extract_path = f"{TEMP_DIR}/{nombre_seguro}"
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            
            print(f"📦 ZIP descomprimido")
            
            # 12. Buscar el archivo "pliego" en 1_Publicaciones/Adjuntos
            pliego_path = None
            adjuntos_path = f"{extract_path}/1_Publicaciones/Adjuntos"
            
            if os.path.exists(adjuntos_path):
                print(f"📂 Buscando pliego en: {adjuntos_path}")
                archivos = os.listdir(adjuntos_path)
                print(f"   Archivos encontrados: {archivos}")
                
                for file in archivos:
                    if "pliego" in file.lower():
                        pliego_path = os.path.join(adjuntos_path, file)
                        print(f"📄 Pliego encontrado: {file}")
                        break
                
                if not pliego_path:
                    # Si no encontró "pliego", listar todos los archivos
                    print(f"⚠️ No se encontró archivo con 'pliego' en el nombre")
                    print(f"   Archivos disponibles: {archivos}")
            else:
                print(f"❌ No existe la carpeta: {adjuntos_path}")
                
                # Listar lo que sí existe
                print(f"📂 Estructura del ZIP:")
                for root, dirs, files in os.walk(extract_path):
                    level = root.replace(extract_path, '').count(os.sep)
                    indent = ' ' * 2 * level
                    print(f"{indent}{os.path.basename(root)}/")
                    subindent = ' ' * 2 * (level + 1)
                    for file in files:
                        print(f"{subindent}{file}")
            
            browser.close()
            
            return pliego_path, nombre_seguro
            
        except Exception as e:
            browser.close()
            raise Exception(f"Error al descargar: {str(e)}")

# Endpoint principal
@app.route('/descargar-pliego', methods=['POST'])
def descargar_pliego_endpoint():
    """
    Este endpoint recibe:
    - referencia: La referencia de la licitación (ej: SRSEN-DAF-CM-2026-0002)
    
    Y devuelve el archivo pliego
    """
    
    data = request.json
    referencia = data.get('referencia')
    
    if not referencia:
        return jsonify({"error": "Falta el parámetro 'referencia'"}), 400
    
    try:
        pliego_path, nombre_seguro = descargar_pliego(referencia)
        
        if pliego_path and os.path.exists(pliego_path):
            return send_file(
                pliego_path, 
                as_attachment=True,
                download_name=f"pliego_{nombre_seguro}.pdf"
            )
        else:
            return jsonify({
                "error": "No se encontró el pliego",
                "mensaje": "Revisa los logs en Railway para ver la estructura del ZIP"
            }), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ruta de prueba
@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "compita-descarga-pliegos"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)