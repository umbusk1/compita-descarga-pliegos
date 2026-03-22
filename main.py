from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from playwright.sync_api import sync_playwright
import os
import zipfile
import time
import re
from datetime import datetime, timedelta
import base64
import json
import requests
from pypdf import PdfReader

app = Flask(__name__)
CORS(app, origins=["https://compita.umbusk.com"])

# Ruta donde se guardarán los archivos (persistentes por 30 días)
TEMP_DIR = "/tmp/descargas"
CACHE_DIAS = 30  # Días para mantener archivos en cache

def limpiar_archivos_viejos():
    """
    Limpia archivos con más de CACHE_DIAS días
    """
    try:
        if not os.path.exists(TEMP_DIR):
            return
        
        ahora = time.time()
        archivos_borrados = 0
        
        for archivo in os.listdir(TEMP_DIR):
            ruta_completa = os.path.join(TEMP_DIR, archivo)
            
            # Verificar edad del archivo
            edad_segundos = ahora - os.path.getmtime(ruta_completa)
            edad_dias = edad_segundos / (60 * 60 * 24)
            
            if edad_dias > CACHE_DIAS:
                try:
                    os.remove(ruta_completa)
                    archivos_borrados += 1
                    print(f"🗑️ Borrado: {archivo} (edad: {edad_dias:.1f} días)")
                except Exception as e:
                    print(f"⚠️ Error borrando {archivo}: {str(e)}")
        
        if archivos_borrados > 0:
            print(f"✅ Limpieza completada: {archivos_borrados} archivos borrados")
    
    except Exception as e:
        print(f"⚠️ Error en limpieza automática: {str(e)}")

def verificar_archivo_en_cache(referencia):
    """
    Verifica si el archivo ya existe en cache (menos de 30 días)
    Retorna la ruta del archivo si existe, None si no
    """
    try:
        nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
        
        # Buscar archivos que coincidan con la referencia
        for archivo in os.listdir(TEMP_DIR):
            if archivo.startswith(nombre_seguro) and archivo.endswith('_documento.pdf'):
                ruta_completa = os.path.join(TEMP_DIR, archivo)
                
                # Verificar edad
                edad_segundos = time.time() - os.path.getmtime(ruta_completa)
                edad_dias = edad_segundos / (60 * 60 * 24)
                
                if edad_dias <= CACHE_DIAS:
                    print(f"📦 Archivo en cache encontrado (edad: {edad_dias:.1f} días)")
                    return ruta_completa
        
        return None
    
    except Exception as e:
        print(f"⚠️ Error verificando cache: {str(e)}")
        return None

def descargar_pliego(referencia):
    """
    Descarga el documento principal de una licitación (pliego, ficha, términos, etc.)
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
            
            # 8. Buscar el frame que contiene el botón de descarga
            print(f"🔎 Buscando iframe del detalle...")
            page.wait_for_timeout(3000)
            
            # En Playwright, los frames se acceden con page.frames
            frames = page.frames
            print(f"   Total frames: {len(frames)}")
            
            iframe_correcto = None
            for i, frame in enumerate(frames):
                try:
                    print(f"   Probando frame {i+1}...")
                    
                    # Buscar directamente el botón de descarga en este frame
                    # Si lo encuentra, este es el frame correcto
                    boton_test = frame.locator('#tbToolBar_btnTbDownload').first
                    
                    if boton_test.count() > 0:
                        print(f"   ✅ FRAME CORRECTO encontrado (tiene botón de descarga)")
                        iframe_correcto = frame
                        break
                    else:
                        print(f"   ❌ Frame no tiene el botón")
                except Exception as e:
                    print(f"   ❌ Error en frame {i+1}: {str(e)[:80]}")
                    continue
            
            if not iframe_correcto:
                # Si no encontró por botón, intentar por referencia en el texto
                print(f"   Reintentando búsqueda por contenido de texto...")
                for i, frame in enumerate(frames):
                    try:
                        # Intentar obtener el texto del body
                        body_text = frame.locator('body').text_content(timeout=5000)
                        if body_text and referencia in body_text:
                            print(f"   ✅ Frame {i+1} contiene la referencia")
                            iframe_correcto = frame
                            break
                    except:
                        continue
            
            if not iframe_correcto:
                raise Exception("No se encontró iframe con el botón de descarga")
            
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
            
            # 11. Extraer el documento principal del ZIP
            print(f"📦 Extrayendo documento principal...")
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                archivos_zip = zip_ref.namelist()
                print(f"   Archivos en ZIP: {len(archivos_zip)}")
                
                # Buscar el documento principal en /1_Publicaciones/Adjuntos/
                documento_encontrado = None
                
                # Palabras clave a buscar (en orden de prioridad)
                palabras_clave = ['pliego', 'ficha', 'terminos', 'términos', 'especificaciones', 'anexo']
                
                # ESTRATEGIA 1: Buscar por palabras clave
                for palabra in palabras_clave:
                    if documento_encontrado:
                        break
                    
                    for archivo in archivos_zip:
                        if '1_Publicaciones/Adjuntos/' in archivo:
                            nombre_archivo = os.path.basename(archivo).lower()
                            
                            if palabra in nombre_archivo and archivo.endswith('.pdf'):
                                print(f"   ✅ Documento encontrado por '{palabra}': {os.path.basename(archivo)}")
                                
                                # Extraer solo ese archivo
                                documento_path = f"{TEMP_DIR}/{nombre_seguro}_{int(time.time())}_documento.pdf"
                                with zip_ref.open(archivo) as source:
                                    with open(documento_path, 'wb') as target:
                                        target.write(source.read())
                                
                                documento_encontrado = documento_path
                                break
                
                # ESTRATEGIA 2: Si no encontró por palabra clave, buscar el PDF más grande en Adjuntos
                if not documento_encontrado:
                    print(f"   ⚠️ No se encontró por palabras clave, buscando PDF más grande...")
                    
                    pdfs_en_adjuntos = []
                    for archivo in archivos_zip:
                        if '1_Publicaciones/Adjuntos/' in archivo and archivo.endswith('.pdf'):
                            # Obtener el tamaño del archivo
                            info = zip_ref.getinfo(archivo)
                            pdfs_en_adjuntos.append({
                                'nombre': archivo,
                                'tamano': info.file_size
                            })
                    
                    if pdfs_en_adjuntos:
                        # Ordenar por tamaño (más grande primero)
                        pdfs_en_adjuntos.sort(key=lambda x: x['tamano'], reverse=True)
                        archivo_mas_grande = pdfs_en_adjuntos[0]['nombre']
                        
                        print(f"   ✅ Usando PDF más grande: {os.path.basename(archivo_mas_grande)}")
                        print(f"      Tamaño: {pdfs_en_adjuntos[0]['tamano'] / 1024:.1f} KB")
                        
                        # Extraer el archivo más grande
                        documento_path = f"{TEMP_DIR}/{nombre_seguro}_{int(time.time())}_documento.pdf"
                        with zip_ref.open(archivo_mas_grande) as source:
                            with open(documento_path, 'wb') as target:
                                target.write(source.read())
                        
                        documento_encontrado = documento_path
                
                if not documento_encontrado:
                    raise Exception("No se encontró ningún documento principal en el ZIP")
            
            print(f"📄 Documento extraído exitosamente")
            
            # Borrar el ZIP (ya no lo necesitamos, solo guardamos el PDF)
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                    print(f"🗑️ ZIP eliminado (solo guardamos el PDF)")
            except Exception as e:
                print(f"⚠️ Error borrando ZIP: {str(e)}")
            
            # Cerrar navegador
            browser.close()
            
            return documento_encontrado
            
        except Exception as e:
            browser.close()
            raise Exception(f"Error al descargar: {str(e)}")

@app.route('/descargar-pliego', methods=['POST'])
def endpoint_descargar_pliego():
    """
    Endpoint para descargar el documento principal de una licitación
    Guarda archivos en cache por 30 días para análisis posterior
    
    POST /descargar-pliego
    Body: {"referencia": "SRSEN-DAF-CM-2026-0002"}
    """
    try:
        data = request.get_json()
        referencia = data.get('referencia')
        
        if not referencia:
            return jsonify({"error": "Falta el parámetro 'referencia'"}), 400
        
        # Ejecutar limpieza automática de archivos viejos
        limpiar_archivos_viejos()
        
        # Verificar si el archivo ya existe en cache
        documento_path = verificar_archivo_en_cache(referencia)
        
        if documento_path:
            print(f"✅ Usando documento en cache")
        else:
            # No está en cache, descargar
            print(f"🔽 Descargando documento (no está en cache)")
            documento_path = descargar_pliego(referencia)
        
        # Retornar el archivo (NO lo borramos, se queda en cache)
        nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
        
        return send_file(
            documento_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"documento_{nombre_seguro}.pdf"
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/analizar-pliego', methods=['POST'])
def analizar_pliego():
    """
    Analiza un pliego con Claude AI.
    Extrae el texto del PDF y lo envía como texto plano (más eficiente).
    
    POST /analizar-pliego
    Body: {
        "referencia": "SRSEN-DAF-CM-2026-0002",
        "titulo": "Título de la licitación",
        "descripcion": "Descripción",
        "monto": 1725000
    }
    """
    try:
        data = request.get_json()
        referencia = data.get('referencia')
        titulo = data.get('titulo', '')
        descripcion = data.get('descripcion', '')
        monto = data.get('monto', 0)
        empresa_descripcion = data.get('empresa_descripcion', '')
        empresa_website = data.get('empresa_website', '')
        
        if not referencia:
            return jsonify({'success': False, 'error': 'Falta referencia'}), 400
        
        print(f"📊 Iniciando análisis de {referencia}")
        
        # 1. Verificar si el archivo ya está en cache
        archivo_pdf = verificar_archivo_en_cache(referencia)
        
        # 2. Si no está en cache, descargarlo
        if not archivo_pdf:
            print(f"📥 Archivo no encontrado en cache, descargando...")
            archivo_pdf = descargar_pliego(referencia)
        else:
            print(f"✅ Usando archivo desde cache: {archivo_pdf}")
        
        # 3. Verificar tamaño del PDF
        tamano_bytes = os.path.getsize(archivo_pdf)
        tamano_mb = tamano_bytes / (1024 * 1024)
        print(f"📏 Tamaño del PDF: {tamano_mb:.2f} MB")
        
        # Límite generoso: el texto extraído siempre será mucho menor que el PDF
        if tamano_mb > 50:
            print(f"⚠️ PDF excesivamente grande: {tamano_mb:.2f} MB")
            return jsonify({
                'success': False,
                'error': f'El pliego es demasiado grande ({tamano_mb:.1f} MB). Límite: 50 MB.'
            }), 400
        
        # 4. Extraer texto del PDF
        print(f"📄 Extrayendo texto del PDF...")
        try:
            reader = PdfReader(archivo_pdf)
            texto_completo = ""
            
            for i, page in enumerate(reader.pages):
                try:
                    texto_pagina = page.extract_text()
                    if texto_pagina:
                        texto_completo += texto_pagina + "\n\n"
                except Exception as e:
                    print(f"⚠️ Error extrayendo página {i+1}: {str(e)}")
                    continue
            
            if not texto_completo.strip():
                return jsonify({
                    'success': False,
                    'error': 'No se pudo extraer texto del PDF. El documento puede estar protegido o ser solo imágenes.'
                }), 400
            
            # Limitar texto a ~100,000 caracteres (aprox 25,000 tokens)
            if len(texto_completo) > 100000:
                print(f"⚠️ Texto muy largo ({len(texto_completo)} caracteres), truncando...")
                texto_completo = texto_completo[:100000] + "\n\n[DOCUMENTO TRUNCADO - Análisis basado en las primeras páginas]"
            
            print(f"✅ Texto extraído: {len(texto_completo)} caracteres, {len(reader.pages)} páginas")
            
        except Exception as e:
            print(f"❌ Error al leer PDF: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Error al procesar el PDF: {str(e)}'
            }), 400
        
        # 5. Crear el prompt para Claude
perfil_empresa = ""
        if empresa_descripcion:
            perfil_empresa += f"\n- Descripción: {empresa_descripcion}"
        if empresa_website:
            perfil_empresa += f"\n- Sitio web: {empresa_website}"

        seccion_perfil = f"""
PERFIL DE LA EMPRESA QUE EVALÚA:
{perfil_empresa if perfil_empresa else "No disponible"}
""" if perfil_empresa else ""

        prompt_analisis = f"""Eres un experto analista de licitaciones públicas dominicanas.

CONTEXTO DE LA LICITACIÓN:
- Referencia: {referencia}
- Título: {titulo}
- Descripción: {descripcion}
- Monto estimado: RD${monto:,.2f}
{seccion_perfil}
A continuación está el contenido completo del pliego de condiciones:

---INICIO DEL PLIEGO---
{texto_completo}
---FIN DEL PLIEGO---

INSTRUCCIONES:
Analiza el pliego y proporciona un análisis estructurado en formato JSON con esta estructura exacta:

{{
  "sintesis": "Resumen ejecutivo en 2-3 oraciones sobre qué se está licitando y para qué institución",
  "oportunidades": [
    "Primera oportunidad identificada (específica del pliego)",
    "Segunda oportunidad identificada (específica del pliego)",
    "Tercera oportunidad identificada (específica del pliego)"
  ],
  "riesgos": [
    "Primer riesgo o desafío identificado (específico del pliego)",
    "Segundo riesgo o desafío identificado (específico del pliego)",
    "Tercer riesgo o desafío identificado (específico del pliego)"
  ],
  "requisitos": [
    "Primer requisito clave para participar (específico del pliego)",
    "Segundo requisito clave para participar (específico del pliego)",
    "Tercer requisito clave para participar (específico del pliego)"
  ],
  "viabilidad": {{
    "veredicto": "VIABLE | VIABLE CON RIESGOS | DIFÍCIL DE CUMPLIR",
    "tiempo_presentacion": "X días hábiles hasta el cierre — [HOLGADO | AJUSTADO | MUY AJUSTADO]",
    "garantias": "Descripción de garantías o fianzas exigidas y si son proporcionales al monto",
    "experiencia_previa": "Qué experiencia previa exige el pliego y si es un obstáculo",
    "especificaciones_tecnicas": "Si las marcas, modelos o especificaciones coinciden con el perfil de la empresa"
  }},
  "recomendacion": "Recomendación clara sobre si vale la pena participar y por qué, considerando el perfil de la empresa y los requisitos del pliego",
  "puntuacion": 75
}}

CRITERIOS PARA LA PUNTUACIÓN (0-100):
- 90-100: Excelente oportunidad, alta probabilidad de éxito, pliego claro y requisitos razonables
- 70-89: Buena oportunidad, considerar participar, balance favorable entre esfuerzo y beneficio
- 50-69: Oportunidad moderada, evaluar capacidades cuidadosamente
- 30-49: Oportunidad limitada, alta competencia o requisitos complejos
- 0-29: No recomendado, riesgos superan beneficios o requisitos inviables

IMPORTANTE:
- Responde SOLO con el JSON, sin texto adicional ni markdown
- Sé específico y práctico en cada punto basándote en el contenido real del pliego
- Para la sección "viabilidad", revisa explícitamente: fechas de presentación, garantías exigidas, experiencia previa requerida, y especificaciones técnicas
- Si el perfil de la empresa está disponible, úsalo para evaluar si las especificaciones técnicas coinciden
- Si el pliego es muy técnico, destaca los requisitos más críticos para participar"""

        # 6. Llamar a Claude API
        api_url = "https://api.anthropic.com/v1/messages"
        
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'API key de Anthropic no configurada en Railway'
            }), 500
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": prompt_analisis
                }
            ]
        }
        
        print("🤖 Enviando texto del pliego a Claude AI...")
        response = requests.post(api_url, headers=headers, json=payload, timeout=120)
        
        if response.status_code != 200:
            error_detail = response.text[:500]
            print(f"❌ Error de Claude API: {response.status_code} - {error_detail}")
            raise Exception(f"Error de Claude API: {response.status_code}")
        
        # 7. Extraer el análisis de la respuesta
        claude_response = response.json()
        analisis_texto = claude_response['content'][0]['text']
        
        # 8. Parsear el JSON del análisis
        analisis_texto = analisis_texto.replace('```json', '').replace('```', '').strip()
        analisis = json.loads(analisis_texto)
        
        print(f"✅ Análisis completado con puntuación: {analisis.get('puntuacion', 0)}")
        
        # 9. Retornar resultado
        return jsonify({
            'success': True,
            'pliego_analizado': True,
            'analisis': analisis
        })
        
    except json.JSONDecodeError as e:
        print(f"❌ Error parseando JSON del análisis: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error al procesar respuesta de Claude AI'
        }), 500
        
    except Exception as e:
        print(f"❌ Error en análisis: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "compita-descarga-pliegos"})

@app.route('/cache/info', methods=['GET'])
def cache_info():
    """
    Retorna información sobre archivos en cache
    """
    try:
        if not os.path.exists(TEMP_DIR):
            return jsonify({"archivos": 0, "tamano_total_mb": 0, "archivos_list": []})
        
        archivos_info = []
        tamano_total = 0
        
        for archivo in os.listdir(TEMP_DIR):
            ruta_completa = os.path.join(TEMP_DIR, archivo)
            tamano = os.path.getsize(ruta_completa)
            edad_segundos = time.time() - os.path.getmtime(ruta_completa)
            edad_dias = edad_segundos / (60 * 60 * 24)
            
            archivos_info.append({
                "nombre": archivo,
                "tamano_mb": round(tamano / (1024 * 1024), 2),
                "edad_dias": round(edad_dias, 1)
            })
            
            tamano_total += tamano
        
        return jsonify({
            "archivos": len(archivos_info),
            "tamano_total_mb": round(tamano_total / (1024 * 1024), 2),
            "cache_dias": CACHE_DIAS,
            "archivos_list": archivos_info
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cache/limpiar', methods=['POST'])
def cache_limpiar():
    """
    Fuerza la limpieza de archivos viejos
    """
    try:
        limpiar_archivos_viejos()
        return jsonify({"status": "ok", "mensaje": "Limpieza ejecutada"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)