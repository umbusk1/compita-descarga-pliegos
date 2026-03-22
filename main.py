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
    try:
        if not os.path.exists(TEMP_DIR):
            return
        ahora = time.time()
        archivos_borrados = 0
        for archivo in os.listdir(TEMP_DIR):
            ruta_completa = os.path.join(TEMP_DIR, archivo)
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
    try:
        nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
        for archivo in os.listdir(TEMP_DIR):
            if archivo.startswith(nombre_seguro) and archivo.endswith('_documento.pdf'):
                ruta_completa = os.path.join(TEMP_DIR, archivo)
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
    os.makedirs(TEMP_DIR, exist_ok=True)
    nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.set_default_timeout(120000)
        page = context.new_page()

        try:
            print(f"🔍 Buscando licitación: {referencia}")
            print(f"📋 Navegando al portal...")
            url_listado = "https://comunidad.comprasdominicana.gob.do/Public/Tendering/ContractNoticeManagement/Index"
            page.goto(url_listado, timeout=90000)
            page.wait_for_timeout(5000)
            print(f"✅ Portal cargado")

            print(f"✍️ Escribiendo en el buscador...")
            campo_busqueda = page.locator('#txtAllWords2Search')
            campo_busqueda.wait_for(state='visible', timeout=10000)
            campo_busqueda.clear()
            campo_busqueda.fill(referencia)
            print(f"✅ Referencia ingresada: {referencia}")

            print(f"🔎 Buscando el botón azul 'Buscar'...")
            boton_encontrado = False

            try:
                boton_buscar = page.locator('input[type="button"][value="Buscar"]').first
                if boton_buscar.is_visible(timeout=5000):
                    boton_buscar.click()
                    boton_encontrado = True
                    print(f"✅ Clic en botón azul (Opción 1)")
            except:
                pass

            if not boton_encontrado:
                try:
                    boton_buscar = page.locator('input[value="Buscar"]').first
                    if boton_buscar.is_visible(timeout=5000):
                        boton_buscar.click()
                        boton_encontrado = True
                        print(f"✅ Clic en botón (Opción 2)")
                except:
                    pass

            if not boton_encontrado:
                try:
                    campo_busqueda.press('Enter')
                    boton_encontrado = True
                    print(f"✅ Enter en campo de búsqueda (Opción 3)")
                except:
                    pass

            if not boton_encontrado:
                raise Exception("No se pudo ejecutar la búsqueda - botón no encontrado")

            print(f"⏳ Esperando confirmación del filtro...")
            page.wait_for_timeout(2000)
            filtro_aplicado = False

            try:
                indicador_filtro = page.locator('text=Buscar resultados por').first
                if indicador_filtro.is_visible(timeout=20000):
                    print(f"✅ Filtro confirmado: 'Buscar resultados por'")
                    filtro_aplicado = True
            except:
                pass

            if not filtro_aplicado:
                try:
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

            print(f"🔎 Buscando {referencia} en resultados...")
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

            screenshot_path = f"{TEMP_DIR}/debug_tabla.png"
            page.screenshot(path=screenshot_path)
            print(f"📸 Captura guardada en: {screenshot_path}")

            print(f"🖱️ Buscando botón DETALLE...")
            fila = resultado.locator('xpath=ancestor::tr')

            try:
                html_fila = fila.inner_html()
                print(f"📋 HTML de la fila:")
                print(html_fila[:500])
            except:
                pass

            boton_detalle = None
            selectores_detalle = [
                'a[title="Detalle"]',
                'a[id*="lnkDetailLink"]',
                'xpath=.//a[@title="Detalle"]',
                'xpath=.//a[text()="Detalle"]',
                'a[href="javascript:void(0)"]',
                'a:has-text("Detalle")',
                '*:has-text("Detalle")'
            ]

            for i, selector in enumerate(selectores_detalle):
                try:
                    print(f"   Probando selector {i+1}: {selector}")
                    boton = fila.locator(selector).first
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

            print(f"🖱️ Haciendo scroll al botón...")
            boton_detalle.scroll_into_view_if_needed()
            page.wait_for_timeout(2000)

            print(f"🖱️ Haciendo clic en DETALLE...")
            boton_detalle.click()
            print(f"✅ Clic en DETALLE realizado")

            page.wait_for_timeout(5000)

            pages = context.pages
            if len(pages) > 1:
                page = pages[-1]
                print(f"✅ Cambiado a nueva ventana")

            print(f"🔎 Buscando iframe del detalle...")
            page.wait_for_timeout(3000)

            frames = page.frames
            print(f"   Total frames: {len(frames)}")

            iframe_correcto = None
            for i, frame in enumerate(frames):
                try:
                    print(f"   Probando frame {i+1}...")
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
                print(f"   Reintentando búsqueda por contenido de texto...")
                for i, frame in enumerate(frames):
                    try:
                        body_text = frame.locator('body').text_content(timeout=5000)
                        if body_text and referencia in body_text:
                            print(f"   ✅ Frame {i+1} contiene la referencia")
                            iframe_correcto = frame
                            break
                    except:
                        continue

            if not iframe_correcto:
                raise Exception("No se encontró iframe con el botón de descarga")

            print(f"⬇️ Buscando botón de descarga...")
            boton_descarga = None
            selectores_descarga = [
                '#tbToolBar_btnTbDownload',
                'input[id="tbToolBar_btnTbDownload"]',
                'input[title="Descargar procedimiento"]',
                'input[value="Descargar procedimiento"]',
                'input[type="button"][value="Descargar procedimiento"]'
            ]

            for i, selector in enumerate(selectores_descarga):
                try:
                    print(f"   Probando selector {i+1}: {selector}")
                    boton = iframe_correcto.locator(selector).first
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

            print(f"💾 Iniciando descarga...")
            with page.expect_download(timeout=90000) as download_info:
                boton_descarga.click()

            download = download_info.value
            zip_path = f"{TEMP_DIR}/{nombre_seguro}.zip"
            download.save_as(zip_path)
            print(f"✅ ZIP descargado: {zip_path}")

            if not os.path.exists(zip_path):
                raise Exception("El archivo ZIP no se guardó correctamente")

            tamano_mb = os.path.getsize(zip_path) / (1024*1024)
            print(f"   Tamaño: {tamano_mb:.2f} MB")

            print(f"📦 Extrayendo documento principal...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                archivos_zip = zip_ref.namelist()
                print(f"   Archivos en ZIP: {len(archivos_zip)}")
                documento_encontrado = None
                palabras_clave = ['pliego', 'ficha', 'terminos', 'términos', 'especificaciones', 'anexo']

                for palabra in palabras_clave:
                    if documento_encontrado:
                        break
                    for archivo in archivos_zip:
                        if '1_Publicaciones/Adjuntos/' in archivo:
                            nombre_archivo = os.path.basename(archivo).lower()
                            if palabra in nombre_archivo and archivo.endswith('.pdf'):
                                print(f"   ✅ Documento encontrado por '{palabra}': {os.path.basename(archivo)}")
                                documento_path = f"{TEMP_DIR}/{nombre_seguro}_{int(time.time())}_documento.pdf"
                                with zip_ref.open(archivo) as source:
                                    with open(documento_path, 'wb') as target:
                                        target.write(source.read())
                                documento_encontrado = documento_path
                                break

                if not documento_encontrado:
                    print(f"   ⚠️ No se encontró por palabras clave, buscando PDF más grande...")
                    pdfs_en_adjuntos = []
                    for archivo in archivos_zip:
                        if '1_Publicaciones/Adjuntos/' in archivo and archivo.endswith('.pdf'):
                            info = zip_ref.getinfo(archivo)
                            pdfs_en_adjuntos.append({'nombre': archivo, 'tamano': info.file_size})

                    if pdfs_en_adjuntos:
                        pdfs_en_adjuntos.sort(key=lambda x: x['tamano'], reverse=True)
                        archivo_mas_grande = pdfs_en_adjuntos[0]['nombre']
                        print(f"   ✅ Usando PDF más grande: {os.path.basename(archivo_mas_grande)}")
                        print(f"      Tamaño: {pdfs_en_adjuntos[0]['tamano'] / 1024:.1f} KB")
                        documento_path = f"{TEMP_DIR}/{nombre_seguro}_{int(time.time())}_documento.pdf"
                        with zip_ref.open(archivo_mas_grande) as source:
                            with open(documento_path, 'wb') as target:
                                target.write(source.read())
                        documento_encontrado = documento_path

                if not documento_encontrado:
                    raise Exception("No se encontró ningún documento principal en el ZIP")

            print(f"📄 Documento extraído exitosamente")

            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                    print(f"🗑️ ZIP eliminado (solo guardamos el PDF)")
            except Exception as e:
                print(f"⚠️ Error borrando ZIP: {str(e)}")

            browser.close()
            return documento_encontrado

        except Exception as e:
            browser.close()
            raise Exception(f"Error al descargar: {str(e)}")


@app.route('/descargar-pliego', methods=['POST'])
def endpoint_descargar_pliego():
    try:
        data = request.get_json()
        referencia = data.get('referencia')

        if not referencia:
            return jsonify({"error": "Falta el parámetro 'referencia'"}), 400

        limpiar_archivos_viejos()
        documento_path = verificar_archivo_en_cache(referencia)

        if documento_path:
            print(f"✅ Usando documento en cache")
        else:
            print(f"🔽 Descargando documento (no está en cache)")
            documento_path = descargar_pliego(referencia)

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
    try:
        data = request.get_json()
        referencia = data.get('referencia')
        titulo = data.get('titulo', '')
        descripcion = data.get('descripcion', '')
        monto = data.get('monto', 0)
        empresa_descripcion = data.get('empresa_descripcion', '')
        empresa_website = data.get('empresa_website', '')
        fecha_hoy = datetime.now().strftime('%d/%m/%Y')

        if not referencia:
            return jsonify({'success': False, 'error': 'Falta referencia'}), 400

        print(f"📊 Iniciando análisis de {referencia}")

        # 1. Verificar cache
        archivo_pdf = verificar_archivo_en_cache(referencia)

        # 2. Si no está en cache, descargar
        if not archivo_pdf:
            print(f"📥 Archivo no encontrado en cache, descargando...")
            archivo_pdf = descargar_pliego(referencia)
        else:
            print(f"✅ Usando archivo desde cache: {archivo_pdf}")

        # 3. Verificar tamaño
        tamano_bytes = os.path.getsize(archivo_pdf)
        tamano_mb = tamano_bytes / (1024 * 1024)
        print(f"📏 Tamaño del PDF: {tamano_mb:.2f} MB")

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

        # 5. Preparar perfil de empresa para el prompt
        perfil_empresa = ""
        if empresa_descripcion:
            perfil_empresa += f"\n- Descripción: {empresa_descripcion}"
        if empresa_website:
            perfil_empresa += f"\n- Sitio web: {empresa_website}"

        seccion_perfil = f"""
PERFIL DE LA EMPRESA QUE EVALÚA:
{perfil_empresa if perfil_empresa else "No disponible"}
""" if perfil_empresa else ""

        # 6. Crear el prompt para Claude
        prompt_analisis = f"""Eres un experto analista de licitaciones públicas dominicanas.

CONTEXTO DE LA LICITACIÓN:
- Referencia: {referencia}
- Título: {titulo}
- Descripción: {descripcion}
- Monto estimado: RD${monto:,.2f}
- Fecha de hoy (cuando el usuario solicita este análisis): {fecha_hoy}
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
  "tiempos": {{
    "fecha_limite_oferta": "DD/MM/YYYY — fecha límite para presentar la oferta según el pliego",
    "dias_calendario_restantes": "N días desde hoy ({fecha_hoy}) hasta la fecha límite",
    "alerta": "Elige UNO: HOLGADO, AJUSTADO, o MUY AJUSTADO (menos de 5 días hábiles es MUY AJUSTADO, menos de 10 es AJUSTADO)",
    "fechas_clave": [
      "Lista cada fecha relevante del pliego: apertura de sobres, plazo para preguntas, visitas técnicas, etc."
    ],
    "advertencia": "Si el tiempo es AJUSTADO o MUY AJUSTADO, explica concretamente qué pasos de la preparación de la oferta se verían comprometidos. Dejar vacío si es HOLGADO."
  }},
  "viabilidad": {{
    "veredicto": "Elige UNO: VIABLE, VIABLE CON RIESGOS, o DIFÍCIL DE CUMPLIR",
    "garantias": "Descripción de garantías o fianzas exigidas y si son proporcionales al monto",
    "experiencia_previa": "Qué experiencia previa exige el pliego y si es un obstáculo real",
    "especificaciones_tecnicas": "Si las marcas, modelos o especificaciones coinciden con el perfil de la empresa"
  }},
  "evaluacion": {{
    "a_favor": [
      "Primer argumento técnico a favor de presentar la oferta",
      "Segundo argumento técnico a favor",
      "Tercer argumento técnico a favor"
    ],
    "en_contra": [
      "Primer argumento técnico en contra o factor de riesgo",
      "Segundo argumento técnico en contra",
      "Tercer argumento técnico en contra"
    ]
  }}
}}

IMPORTANTE:
- Responde SOLO con el JSON, sin texto adicional ni markdown
- Sé específico y práctico basándote en el contenido real del pliego
- En "tiempos", usa la fecha de hoy ({fecha_hoy}) para calcular días restantes
- En "evaluacion", usa lenguaje técnico y descriptivo — evita frases como "se recomienda" o "no se recomienda"
- En "viabilidad", revisa explícitamente garantías, experiencia previa y especificaciones técnicas
- Si el perfil de la empresa está disponible, úsalo para evaluar compatibilidad técnica"""

        # 7. Llamar a Claude API
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
            "max_tokens": 3000,
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

        # 8. Extraer y parsear respuesta
        claude_response = response.json()
        analisis_texto = claude_response['content'][0]['text']
        analisis_texto = analisis_texto.replace('```json', '').replace('```', '').strip()

        # Extraer solo el bloque JSON (entre primer { y último })
        inicio = analisis_texto.find('{')
        fin = analisis_texto.rfind('}')
        if inicio == -1 or fin == -1:
            raise json.JSONDecodeError('No se encontró JSON válido', analisis_texto, 0)
        analisis_texto = analisis_texto[inicio:fin+1]

        analisis = json.loads(analisis_texto)

        print(f"✅ Análisis completado con puntuación: {analisis.get('puntuacion', 0)}")

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
    try:
        limpiar_archivos_viejos()
        return jsonify({"status": "ok", "mensaje": "Limpieza ejecutada"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)