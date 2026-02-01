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
    Descarga el pliego usando la MISMA lógica que funcionó en Selenium
    """
    
    # Crear carpeta temporal si no existe
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Limpiar nombre de archivo
    nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
    
    with sync_playwright() as p:
        # Abrir navegador Chrome invisible
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.set_default_timeout(120000)  # 2 minutos
        page = context.new_page()
        
        try:
            print(f"🔍 Buscando licitación: {referencia}")
            
            # 1. Navegar al portal
            print(f"📋 Navegando al portal...")
            url_listado = "https://comunidad.comprasdominicana.gob.do/Public/Tendering/ContractNoticeManagement/Index"
            page.goto(url_listado, timeout=90000)
            page.wait_for_timeout(5000)
            print(f"✅ Portal cargado")
            
            # 2. Usar el buscador - CON ID ESPECÍFICO
            print(f"✍️ Escribiendo en el buscador...")
            campo_busqueda = page.locator('#txtAllWords2Search')
            campo_busqueda.wait_for(state='visible', timeout=10000)
            campo_busqueda.clear()
            campo_busqueda.fill(referencia)
            print(f"✅ Referencia ingresada: {referencia}")
            
            # 3. Hacer clic en el BOTÓN AZUL (input type="button" value="Buscar")
            print(f"🔎 Buscando el botón azul 'Buscar'...")
            
            # Intentar múltiples selectores (como en el código original)
            boton_encontrado = False
            
            # Opción 1: Input type=button con value=Buscar
            try:
                boton_buscar = page.locator('input[type="button"][value="Buscar"]').first
                if boton_buscar.is_visible(timeout=5000):
                    boton_buscar.click()
                    boton_encontrado = True
                    print(f"✅ Clic en botón azul (Opción 1)")
            except:
                pass
            
            # Opción 2: Cualquier input con value=Buscar
            if not boton_encontrado:
                try:
                    boton_buscar = page.locator('input[value="Buscar"]').first
                    if boton_buscar.is_visible(timeout=5000):
                        boton_buscar.click()
                        boton_encontrado = True
                        print(f"✅ Clic en botón (Opción 2)")
                except:
                    pass
            
            # Opción 3: Presionar ENTER en el campo
            if not boton_encontrado:
                try:
                    campo_busqueda.press('Enter')
                    boton_encontrado = True
                    print(f"✅ Enter en campo de búsqueda (Opción 3)")
                except:
                    pass
            
            if not boton_encontrado:
                raise Exception("No se pudo ejecutar la búsqueda - botón no encontrado")
            
            # 4. Esperar que se aplique el filtro - ESPERA EXPLÍCITA
            print(f"⏳ Esperando confirmación del filtro...")
            page.wait_for_timeout(2000)
            
            # Buscar el texto "Buscar resultados por" o el link "Borrar búsqueda"
            filtro_aplicado = False
            
            try:
                # Opción 1: Texto "Buscar resultados por"
                indicador_filtro = page.locator('text=Buscar resultados por').first
                if indicador_filtro.is_visible(timeout=20000):
                    print(f"✅ Filtro confirmado: 'Buscar resultados por'")
                    filtro_aplicado = True
            except:
                pass
            
            if not filtro_aplicado:
                try:
                    # Opción 2: Link "Borrar búsqueda"
                    link_borrar = page.locator('a:has-text("Borrar")').first
                    if link_borrar.is_visible(timeout=5000):
                        print(f"✅ Filtro confirmado: Link 'Borrar búsqueda'")
                        filtro_aplicado = True
                except:
                    pass
            
            if filtro_aplicado:
                print(f"✅ FILTRO APLICADO CORRECTAMENTE")
            else:
                print(f"⚠️ ADVERTENCIA: No se confirmó el filtro, continuando...")
            
            page.wait_for_timeout(3000)
            
            # 5. Buscar la licitación en los resultados
            print(f"🔎 Buscando {referencia} en resultados...")
            
            # Probar múltiples XPaths como en el código original
            resultado = None
            xpaths = [
                f'//td[contains(text(), "{referencia}")]',
                f'//td[text()="{referencia}"]',
                f'//*[contains(text(), "{referencia}")]',
                f'//td[normalize-space(text())="{referencia}"]'
            ]
            
            for i, xpath in enumerate(xpaths):
                try:
                    print(f"   Intentando XPath {i+1}...")
                    resultado_xpath = page.locator(f'xpath={xpath}').first
                    if resultado_xpath.is_visible(timeout=10000):
                        resultado = resultado_xpath
                        print(f"   ✅ XPath {i+1} funcionó")
                        break
                except:
                    print(f"   ❌ XPath {i+1} falló")
                    continue
            
            if not resultado:
                raise Exception(f"No se encontró la licitación {referencia} en los resultados")
            
            print(f"✅ Licitación encontrada en la tabla")
            
            # DEBUG: Captura de pantalla
            screenshot_path = f"{TEMP_DIR}/debug_tabla.png"
            page.screenshot(path=screenshot_path)
            print(f"📸 Captura guardada en: {screenshot_path}")
            
            # 6. Hacer clic en DETALLE
            print(f"🖱️ Buscando botón DETALLE...")
            
            # Encontrar la fila (tr) que contiene el resultado
            fila = resultado.locator('xpath=ancestor::tr')
            
            # DEBUG: Mostrar el HTML de la fila
            try:
                html_fila = fila.inner_html()
                print(f"📋 HTML de la fila:")
                print(html_fila[:500])  # Primeros 500 caracteres
            except:
                pass
            
            # Buscar el botón/link DETALLE en esa fila
            # Basado en el HTML real: <a title="Detalle" href="javascript:void(0);">Detalle</a>
            boton_detalle = None
            selectores_detalle = [
                # Por atributo title (MÁS CONFIABLE)
                'a[title="Detalle"]',
                # Por parte del ID que es consistente
                'a[id*="lnkDetailLink"]',
                # Por XPath con title
                'xpath=.//a[@title="Detalle"]',
                # Por XPath con texto exacto
                'xpath=.//a[text()="Detalle"]',
                # Por href específico
                'a[href="javascript:void(0)"]',
                # Fallbacks originales
                'a:has-text("Detalle")',
                '*:has-text("Detalle")'
            ]
            
            for i, selector in enumerate(selectores_detalle):
                try:
                    print(f"   Probando selector {i+1}: {selector}")
                    boton = fila.locator(selector).first
                    # Usar count() en lugar de is_visible() para evitar timeouts
                    if boton.count() > 0:
                        boton_detalle = boton
                        print(f"   ✅ Selector {i+1} funcionó")
                        break
                    else:
                        print(f"   ❌ Selector {i+1} no encontró elementos")
                except Exception as e:
                    print(f"   ❌ Selector {i+1} dio error: {str(e)[:50]}")
                    continue
            
            if not boton_detalle:
                raise Exception("No se encontró el botón DETALLE con ningún selector")
            
            # Scroll y clic
            print(f"🖱️ Haciendo scroll al botón...")
            boton_detalle.scroll_into_view_if_needed()
            page.wait_for_timeout(2000)
            
            print(f"🖱️ Haciendo clic en DETALLE...")
            boton_detalle.click()
            print(f"✅ Clic en DETALLE realizado")
            
            # 7. Esperar que se abra el modal o nueva ventana
            page.wait_for_timeout(5000)
            
            # Verificar si se abrió una nueva pestaña/ventana
            pages = context.pages
            if len(pages) > 1:
                page = pages[-1]  # Usar la última página abierta
                print(f"✅ Cambiado a nueva ventana")
            
            # 8. Buscar el iframe correcto (que contenga la referencia)
            print(f"🔎 Buscando iframe del detalle...")
            page.wait_for_timeout(3000)
            
            # En Playwright, los iframes se acceden con page.frames()
            frames = page.frames
            print(f"   Total frames: {len(frames)}")
            
            iframe_correcto = None
            for i, frame in enumerate(frames):
                try:
                    print(f"   Probando frame {i+1}...")
                    
                    # Obtener el contenido del frame
                    frame_content = frame.content()
                    
                    if referencia in frame_content:
                        print(f"   ✅ FRAME CORRECTO encontrado (contiene {referencia})")
                        iframe_correcto = frame
                        break
                    else:
                        print(f"   ❌ Frame no contiene la referencia")
                except Exception as e:
                    print(f"   ❌ Error en frame {i+1}: {str(e)[:50]}")
                    continue
            
            if not iframe_correcto:
                raise Exception("No se encontró iframe con la referencia correcta")
            
            # 9. Buscar el botón de descarga en el iframe
            print(f"⬇️ Buscando botón de descarga...")
            
            # Basado en el HTML real: <input id="tbToolBar_btnTbDownload" type="button" value="Descargar procedimiento">
            boton_descarga = None
            selectores_descarga = [
                # Por ID (MÁS CONFIABLE)
                '#tbToolBar_btnTbDownload',
                'input[id="tbToolBar_btnTbDownload"]',
                # Por atributo title
                'input[title="Descargar procedimiento"]',
                # Por value
                'input[value="Descargar procedimiento"]',
                # Por tipo y value
                'input[type="button"][value="Descargar procedimiento"]'
            ]
            
            for i, selector in enumerate(selectores_descarga):
                try:
                    print(f"   Probando selector {i+1}: {selector}")
                    boton = iframe_correcto.locator(selector).first
                    # Usar count() en lugar de is_visible() para evitar timeouts
                    if boton.count() > 0:
                        boton_descarga = boton
                        print(f"   ✅ Selector {i+1} funcionó")
                        break
                    else:
                        print(f"   ❌ Selector {i+1} no encontró elementos")
                except Exception as e:
                    print(f"   ❌ Selector {i+1} error: {str(e)[:50]}")
                    continue
            
            if not boton_descarga:
                raise Exception("No se encontró el botón de descarga")
            
            # 10. Descargar el archivo
            print(f"💾 Iniciando descarga...")
            
            with page.expect_download(timeout=90000) as download_info:
                boton_descarga.click()
            
            download = download_info.value
            
            # Guardar el ZIP
            zip_path = f"{TEMP_DIR}/{nombre_seguro}.zip"
            download.save_as(zip_path)
            print(f"✅ ZIP descargado: {zip_path}")
            
            # Verificar que el archivo existe y tiene contenido
            if not os.path.exists(zip_path):
                raise Exception("El archivo ZIP no se guardó correctamente")
            
            tamano_mb = os.path.getsize(zip_path) / (1024*1024)
            print(f"   Tamaño: {tamano_mb:.2f} MB")
            
            # 11. Extraer el pliego del ZIP
            print(f"📦 Extrayendo pliego...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                archivos_zip = zip_ref.namelist()
                print(f"   Archivos en ZIP: {len(archivos_zip)}")
                
                # Buscar el pliego en /1_Publicaciones/Adjuntos/
                pliego_encontrado = None
                
                for archivo in archivos_zip:
                    if '1_Publicaciones/Adjuntos/' in archivo:
                        nombre_archivo = os.path.basename(archivo)
                        if 'pliego' in nombre_archivo.lower() and archivo.endswith('.pdf'):
                            print(f"   ✅ Pliego encontrado: {nombre_archivo}")
                            
                            # Extraer solo ese archivo
                            pliego_path = f"{TEMP_DIR}/{nombre_seguro}_pliego.pdf"
                            with zip_ref.open(archivo) as source:
                                with open(pliego_path, 'wb') as target:
                                    target.write(source.read())
                            
                            pliego_encontrado = pliego_path
                            break
                
                if not pliego_encontrado:
                    raise Exception("No se encontró el archivo PLIEGO en el ZIP")
            
            print(f"📄 Pliego extraído exitosamente")
            
            # Cerrar navegador
            browser.close()
            
            return pliego_encontrado
            
        except Exception as e:
            browser.close()
            raise Exception(f"Error al descargar: {str(e)}")

@app.route('/descargar-pliego', methods=['POST'])
def endpoint_descargar_pliego():
    """
    Endpoint para descargar el pliego de una licitación
    
    POST /descargar-pliego
    Body: {"referencia": "SRSEN-DAF-CM-2026-0002"}
    """
    try:
        data = request.get_json()
        referencia = data.get('referencia')
        
        if not referencia:
            return jsonify({"error": "Falta el parámetro 'referencia'"}), 400
        
        # Descargar el pliego
        pliego_path = descargar_pliego(referencia)
        
        # Retornar el archivo
        nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
        
        return send_file(
            pliego_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"pliego_{nombre_seguro}.pdf"
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "compita-descarga-pliegos"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)