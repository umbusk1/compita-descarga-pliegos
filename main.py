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
import io
from docx import Document
from docx.shared import Pt
from pypdf import PdfReader
from json_repair import repair_json
from copy import deepcopy

app = Flask(__name__)
CORS(app, origins=["https://compita.umbusk.com"])

TEMP_DIR = "/tmp/descargas"
CACHE_DIAS = 30


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
                    print(f"Borrado: {archivo} (edad: {edad_dias:.1f} dias)")
                except Exception as e:
                    print(f"Error borrando {archivo}: {str(e)}")
        if archivos_borrados > 0:
            print(f"Limpieza completada: {archivos_borrados} archivos borrados")
    except Exception as e:
        print(f"Error en limpieza automatica: {str(e)}")


def verificar_archivo_en_cache(referencia):
    try:
        nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
        for archivo in os.listdir(TEMP_DIR):
            if archivo.startswith(nombre_seguro) and archivo.endswith('_documento.pdf'):
                ruta_completa = os.path.join(TEMP_DIR, archivo)
                edad_segundos = time.time() - os.path.getmtime(ruta_completa)
                edad_dias = edad_segundos / (60 * 60 * 24)
                if edad_dias <= CACHE_DIAS:
                    print(f"Archivo en cache encontrado (edad: {edad_dias:.1f} dias)")
                    return ruta_completa
        return None
    except Exception as e:
        print(f"Error verificando cache: {str(e)}")
        return None


def descargar_pliego(referencia, guardar_zip=False):
    os.makedirs(TEMP_DIR, exist_ok=True)
    nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        context.set_default_timeout(120000)
        page = context.new_page()

        try:
            print(f"Buscando licitacion: {referencia}")
            print(f"Navegando al portal...")
            url_listado = "https://comunidad.comprasdominicana.gob.do/Public/Tendering/ContractNoticeManagement/Index"
            page.goto(url_listado, timeout=90000)
            page.wait_for_timeout(5000)
            print(f"Portal cargado")

            print(f"Escribiendo en el buscador...")
            campo_busqueda = page.locator('#txtAllWords2Search')
            campo_busqueda.wait_for(state='visible', timeout=10000)
            campo_busqueda.clear()
            campo_busqueda.fill(referencia)
            print(f"Referencia ingresada: {referencia}")

            print(f"Buscando boton Buscar...")
            boton_encontrado = False

            try:
                boton_buscar = page.locator('input[type="button"][value="Buscar"]').first
                if boton_buscar.is_visible(timeout=5000):
                    boton_buscar.click()
                    boton_encontrado = True
                    print(f"Clic en boton azul (Opcion 1)")
            except:
                pass

            if not boton_encontrado:
                try:
                    boton_buscar = page.locator('input[value="Buscar"]').first
                    if boton_buscar.is_visible(timeout=5000):
                        boton_buscar.click()
                        boton_encontrado = True
                        print(f"Clic en boton (Opcion 2)")
                except:
                    pass

            if not boton_encontrado:
                try:
                    campo_busqueda.press('Enter')
                    boton_encontrado = True
                    print(f"Enter en campo de busqueda (Opcion 3)")
                except:
                    pass

            if not boton_encontrado:
                raise Exception("No se pudo ejecutar la busqueda - boton no encontrado")

            print(f"Esperando confirmacion del filtro...")
            page.wait_for_timeout(2000)
            filtro_aplicado = False

            try:
                indicador_filtro = page.locator('text=Buscar resultados por').first
                if indicador_filtro.is_visible(timeout=20000):
                    print(f"Filtro confirmado: Buscar resultados por")
                    filtro_aplicado = True
            except:
                pass

            if not filtro_aplicado:
                try:
                    link_borrar = page.locator('a:has-text("Borrar")').first
                    if link_borrar.is_visible(timeout=5000):
                        print(f"Filtro confirmado: Link Borrar busqueda")
                        filtro_aplicado = True
                except:
                    pass

            if filtro_aplicado:
                print(f"FILTRO APLICADO CORRECTAMENTE")
            else:
                print(f"ADVERTENCIA: No se confirmo el filtro, continuando...")

            page.wait_for_timeout(3000)

            print(f"Buscando {referencia} en resultados...")
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
                        print(f"   XPath {i+1} funciono")
                        break
                except:
                    print(f"   XPath {i+1} fallo")
                    continue

            if not resultado:
                raise Exception(f"No se encontro la licitacion {referencia} en los resultados")

            print(f"Licitacion encontrada en la tabla")

            screenshot_path = f"{TEMP_DIR}/debug_tabla.png"
            page.screenshot(path=screenshot_path)

            print(f"Buscando boton DETALLE...")
            fila = resultado.locator('xpath=ancestor::tr')

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
                        print(f"   Selector {i+1} funciono")
                        break
                    else:
                        print(f"   Selector {i+1} no encontro elementos")
                except Exception as e:
                    print(f"   Selector {i+1} error: {str(e)[:50]}")
                    continue

            if not boton_detalle:
                raise Exception("No se encontro el boton DETALLE con ningun selector")

            print(f"Haciendo scroll al boton...")
            boton_detalle.scroll_into_view_if_needed()
            page.wait_for_timeout(2000)

            print(f"Haciendo clic en DETALLE...")
            boton_detalle.click()
            print(f"Clic en DETALLE realizado")

            page.wait_for_timeout(5000)

            pages = context.pages
            if len(pages) > 1:
                page = pages[-1]
                print(f"Cambiado a nueva ventana")

            print(f"Buscando iframe del detalle...")
            page.wait_for_timeout(3000)

            frames = page.frames
            print(f"   Total frames: {len(frames)}")

            iframe_correcto = None
            for i, frame in enumerate(frames):
                try:
                    print(f"   Probando frame {i+1}...")
                    boton_test = frame.locator('#tbToolBar_btnTbDownload').first
                    if boton_test.count() > 0:
                        print(f"   FRAME CORRECTO encontrado")
                        iframe_correcto = frame
                        break
                    else:
                        print(f"   Frame no tiene el boton")
                except Exception as e:
                    print(f"   Error en frame {i+1}: {str(e)[:80]}")
                    continue

            if not iframe_correcto:
                print(f"   Reintentando busqueda por contenido de texto...")
                for i, frame in enumerate(frames):
                    try:
                        body_text = frame.locator('body').text_content(timeout=5000)
                        if body_text and referencia in body_text:
                            print(f"   Frame {i+1} contiene la referencia")
                            iframe_correcto = frame
                            break
                    except:
                        continue

            if not iframe_correcto:
                raise Exception("No se encontro iframe con el boton de descarga")

            print(f"Buscando boton de descarga...")
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
                        print(f"   Selector {i+1} funciono")
                        break
                    else:
                        print(f"   Selector {i+1} no encontro elementos")
                except Exception as e:
                    print(f"   Selector {i+1} error: {str(e)[:50]}")
                    continue

            if not boton_descarga:
                raise Exception("No se encontro el boton de descarga")

            print(f"Iniciando descarga...")
            with page.expect_download(timeout=90000) as download_info:
                boton_descarga.click()

            download = download_info.value
            zip_path = f"{TEMP_DIR}/{nombre_seguro}.zip"
            download.save_as(zip_path)
            print(f"ZIP descargado: {zip_path}")

            if not os.path.exists(zip_path):
                raise Exception("El archivo ZIP no se guardo correctamente")

            tamano_mb = os.path.getsize(zip_path) / (1024 * 1024)
            print(f"   Tamano: {tamano_mb:.2f} MB")

            print(f"Extrayendo documento principal...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                archivos_zip = zip_ref.namelist()
                print(f"   Archivos en ZIP: {len(archivos_zip)}")
                documento_encontrado = None
                palabras_clave = ['pliego', 'ficha', 'terminos', 'especificaciones', 'anexo']

                for palabra in palabras_clave:
                    if documento_encontrado:
                        break
                    for archivo in archivos_zip:
                        if '1_Publicaciones/Adjuntos/' in archivo:
                            nombre_archivo = os.path.basename(archivo).lower()
                            if palabra in nombre_archivo and archivo.endswith('.pdf'):
                                print(f"   Documento encontrado por '{palabra}': {os.path.basename(archivo)}")
                                documento_path = f"{TEMP_DIR}/{nombre_seguro}_{int(time.time())}_documento.pdf"
                                with zip_ref.open(archivo) as source:
                                    with open(documento_path, 'wb') as target:
                                        target.write(source.read())
                                documento_encontrado = documento_path
                                break

                if not documento_encontrado:
                    print(f"   No se encontro por palabras clave, buscando PDF mas grande...")
                    pdfs_en_adjuntos = []
                    for archivo in archivos_zip:
                        if '1_Publicaciones/Adjuntos/' in archivo and archivo.endswith('.pdf'):
                            info = zip_ref.getinfo(archivo)
                            pdfs_en_adjuntos.append({'nombre': archivo, 'tamano': info.file_size})

                    if pdfs_en_adjuntos:
                        pdfs_en_adjuntos.sort(key=lambda x: x['tamano'], reverse=True)
                        archivo_mas_grande = pdfs_en_adjuntos[0]['nombre']
                        print(f"   Usando PDF mas grande: {os.path.basename(archivo_mas_grande)}")
                        documento_path = f"{TEMP_DIR}/{nombre_seguro}_{int(time.time())}_documento.pdf"
                        with zip_ref.open(archivo_mas_grande) as source:
                            with open(documento_path, 'wb') as target:
                                target.write(source.read())
                        documento_encontrado = documento_path

                if not documento_encontrado:
                    raise Exception("No se encontro ningun documento principal en el ZIP")

                print(f"Documento extraido exitosamente")

                if not guardar_zip:
                    try:
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                            print(f"ZIP eliminado")
                    except Exception as e:
                        print(f"Error borrando ZIP: {str(e)}")
                else:
                    print(f"ZIP conservado: {zip_path}")

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
            return jsonify({"error": "Falta el parametro 'referencia'"}), 400

        limpiar_archivos_viejos()
        documento_path = verificar_archivo_en_cache(referencia)

        if documento_path:
            print(f"Usando documento en cache")
        else:
            print(f"Descargando documento (no esta en cache)")
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
        fecha_presentacion = data.get('fecha_presentacion', '')
        fecha_hoy = datetime.now().strftime('%d/%m/%Y')

        if not referencia:
            return jsonify({'success': False, 'error': 'Falta referencia'}), 400

        print(f"Iniciando analisis de {referencia}")

        archivo_pdf = verificar_archivo_en_cache(referencia)

        if not archivo_pdf:
            print(f"Archivo no encontrado en cache, descargando...")
            archivo_pdf = descargar_pliego(referencia)
        else:
            print(f"Usando archivo desde cache: {archivo_pdf}")

        tamano_bytes = os.path.getsize(archivo_pdf)
        tamano_mb = tamano_bytes / (1024 * 1024)
        print(f"Tamano del PDF: {tamano_mb:.2f} MB")

        if tamano_mb > 50:
            return jsonify({
                'success': False,
                'error': f'El pliego es demasiado grande ({tamano_mb:.1f} MB). Limite: 50 MB.'
            }), 400

        print(f"Extrayendo texto del PDF...")
        try:
            reader = PdfReader(archivo_pdf)
            texto_completo = ""

            for i, page in enumerate(reader.pages):
                try:
                    texto_pagina = page.extract_text()
                    if texto_pagina:
                        texto_completo += texto_pagina + "\n\n"
                except Exception as e:
                    print(f"Error extrayendo pagina {i+1}: {str(e)}")
                    continue

            if not texto_completo.strip():
                return jsonify({
                    'success': False,
                    'error': 'No se pudo extraer texto del PDF.'
                }), 400

            if len(texto_completo) > 100000:
                print(f"Texto muy largo ({len(texto_completo)} caracteres), truncando...")
                texto_completo = texto_completo[:100000] + "\n\n[DOCUMENTO TRUNCADO]"

            print(f"Texto extraido: {len(texto_completo)} caracteres, {len(reader.pages)} paginas")

        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Error al procesar el PDF: {str(e)}'
            }), 400

        perfil_empresa = ""
        if empresa_descripcion:
            perfil_empresa += f"\n- Descripcion: {empresa_descripcion}"
        if empresa_website:
            perfil_empresa += f"\n- Sitio web: {empresa_website}"

        seccion_perfil = f"""
PERFIL DE LA EMPRESA QUE EVALUA:
{perfil_empresa if perfil_empresa else "No disponible"}
""" if perfil_empresa else ""

        prompt_analisis = f"""Eres un experto analista de licitaciones publicas dominicanas.

CONTEXTO DE LA LICITACION:
- Referencia: {referencia}
- Titulo: {titulo}
- Descripcion: {descripcion}
- Monto estimado: RD${monto:,.2f}
- Fecha de hoy: {fecha_hoy}
- Fecha limite de presentacion: {fecha_presentacion if fecha_presentacion else 'No disponible'}
{seccion_perfil}
A continuacion esta el contenido completo del pliego de condiciones:

---INICIO DEL PLIEGO---
{texto_completo}
---FIN DEL PLIEGO---

INSTRUCCIONES:
Analiza el pliego y proporciona un analisis estructurado en formato JSON con esta estructura exacta:

{{
  "sintesis": "Resumen ejecutivo en 2-3 oraciones",
  "oportunidades": ["Primera oportunidad", "Segunda oportunidad", "Tercera oportunidad"],
  "riesgos": ["Primer riesgo", "Segundo riesgo", "Tercer riesgo"],
  "requisitos": ["Primer requisito", "Segundo requisito", "Tercer requisito"],
  "certificaciones_iso": {{
    "exige_iso": "SI o NO",
    "listado": ["ISO XXXX - descripcion"],
    "nota": "Normas tecnicas equivalentes si aplica"
  }},
  "tiempos": {{
    "fecha_limite_oferta": "DD/MM/YYYY",
    "dias_calendario_restantes": "N dias desde hoy ({fecha_hoy})",
    "alerta": "HOLGADO, AJUSTADO, o MUY AJUSTADO",
    "fechas_clave": ["Lista de fechas relevantes del pliego"],
    "advertencia": "Si tiempo ajustado, explicar impacto. Vacio si holgado."
  }},
  "viabilidad": {{
    "veredicto": "VIABLE, VIABLE CON RIESGOS, o DIFICIL DE CUMPLIR",
    "garantias": "Descripcion de garantias exigidas",
    "experiencia_previa": "Experiencia previa que exige el pliego",
    "especificaciones_tecnicas": "Compatibilidad con perfil de la empresa"
  }},
  "evaluacion": {{
    "a_favor": ["Argumento 1", "Argumento 2", "Argumento 3"],
    "en_contra": ["Riesgo 1", "Riesgo 2", "Riesgo 3"]
  }}
}}

IMPORTANTE: Responde SOLO con el JSON, sin texto adicional ni markdown."""

        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'API key de Anthropic no configurada'
            }), 500

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }

        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 3000,
            "messages": [{"role": "user", "content": prompt_analisis}]
        }

        print("Enviando texto del pliego a Claude AI...")
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=120
        )

        if response.status_code != 200:
            raise Exception(f"Error de Claude API: {response.status_code}")

        claude_response = response.json()
        analisis_texto = claude_response['content'][0]['text']
        analisis_texto = analisis_texto.replace('```json', '').replace('```', '').strip()

        inicio = analisis_texto.find('{')
        fin = analisis_texto.rfind('}')
        if inicio == -1 or fin == -1:
            raise json.JSONDecodeError('No se encontro JSON valido', analisis_texto, 0)
        analisis_texto = analisis_texto[inicio:fin+1]

        analisis = json.loads(analisis_texto)

        print(f"Analisis completado")

        return jsonify({
            'success': True,
            'pliego_analizado': True,
            'analisis': analisis
        })

    except json.JSONDecodeError as e:
        print(f"Error parseando JSON del analisis: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error al procesar respuesta de Claude AI'
        }), 500

    except Exception as e:
        print(f"Error en analisis: {str(e)}")
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


# ── FUNCION AUXILIAR: extrae items del PDF con Claude ────────────────────────

def extraer_items_con_claude(pdf_bytes_list, referencia):

    def extraer_de_un_pdf(pdf_bytes, indice, contexto_previo=""):
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            texto = ""
            for pg in reader.pages:
                t = pg.extract_text()
                if t:
                    texto += t + "\n"
        except Exception as e:
            print(f"Error leyendo PDF {indice + 1}: {e}")
            return []

        if not texto.strip():
            print(f"PDF {indice + 1} sin texto extraible - omitido")
            return []

        if contexto_previo:
            contexto_str = f"""
CONTEXTO IMPORTANTE: Los documentos anteriores ya extrajeron los siguientes items:
{contexto_previo}
Este documento es una CONTINUACION. Si no ves un encabezado de lote al inicio,
asigna los items al lote donde corresponde segun la numeracion que continua.
"""
        else:
            contexto_str = ""

        prompt = f"""Eres un experto en licitaciones publicas dominicanas.
{contexto_str}
Contenido de un documento de la licitacion {referencia} (documento {indice + 1}):

{texto[:120000]}

INSTRUCCION:
Extrae TODOS los items, productos, equipos o materiales que aparecen en ESTE documento.
Pueden estar organizados en LOTES (LOTE I, LOTE II, LOTE III, etc.).
IMPORTANTE: identifica correctamente el lote de cada item segun los encabezados
"LOTE- I", "LOTE- II", "LOTE- III" que aparecen en el documento.
No asumas que todos los items son del mismo lote.

Para cada item devuelve:
- lote: numero romano del lote (ej: "I", "II", "III"). Si no hay lotes, usa "I".
- numero: numero del item dentro de su lote
- descripcion: descripcion completa (incluye marca y modelo si aparecen)
- unidad: unidad de medida (UD, SVC, PAQ, KG, etc.)
- cantidad: cantidad numerica (o null si no aparece)

Si este documento no contiene ningun producto, equipo o material, devuelve lista vacia.

Responde UNICAMENTE con JSON valido, sin texto adicional:
{{
  "items": [
    {{"lote": "I", "numero": "1", "descripcion": "...", "unidad": "UD", "cantidad": 1}},
    {{"lote": "II", "numero": "1", "descripcion": "...", "unidad": "UD", "cantidad": 1}}
  ]
}}"""

        api_key = os.environ.get('ANTHROPIC_API_KEY')
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 16000,
            "messages": [{"role": "user", "content": prompt}]
        }

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=300
        )
        if resp.status_code != 200:
            print(f"Error Claude API en PDF {indice + 1}: {resp.status_code}")
            return []

        texto_resp = resp.json()['content'][0]['text']
        texto_resp = texto_resp.replace('```json', '').replace('```', '').strip()
        inicio = texto_resp.find('{')
        fin = texto_resp.rfind('}')
        if inicio == -1 or fin == -1:
            return []
        json_raw = texto_resp[inicio:fin + 1]
        try:
            data = json.loads(json_raw)
        except json.JSONDecodeError:
            print(f"JSON malformado en PDF {indice + 1}, aplicando reparacion...")
            json_reparado = repair_json(json_raw)
            data = json.loads(json_reparado)
        return data.get('items', [])

    todos_items = {}
    contexto_previo = ""

    for i, pdf_bytes in enumerate(pdf_bytes_list):
        print(f"  Procesando PDF {i + 1}/{len(pdf_bytes_list)} con Claude...")
        items_pdf = extraer_de_un_pdf(pdf_bytes, i, contexto_previo)
        print(f"     -> {len(items_pdf)} items encontrados")

        for item in items_pdf:
            lote = str(item.get('lote', 'I')).strip().upper()
            num = str(item.get('numero', '')).strip()
            if not num:
                continue
            clave = f"{lote}-{num}"
            if clave not in todos_items or not todos_items[clave].get('descripcion'):
                todos_items[clave] = item

        if items_pdf:
            resumen = {}
            for item in items_pdf:
                lote = str(item.get('lote', 'I')).strip().upper()
                resumen.setdefault(lote, []).append(
                    int(item.get('numero', 0)) if str(item.get('numero', 0)).isdigit() else 0
                )
            partes = []
            for lote in sorted(resumen):
                nums = sorted(resumen[lote])
                partes.append(f"Lote {lote}: items {nums[0]} al {nums[-1]} ({len(nums)} items)")
            contexto_previo = "; ".join(partes)

    orden_lote = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5}

    def clave_orden(item):
        lote = str(item.get('lote', 'I')).strip().upper()
        try:
            num = int(item.get('numero', 0))
        except (ValueError, TypeError):
            num = 9999
        return (orden_lote.get(lote, 99), num)

    return sorted(todos_items.values(), key=clave_orden)


def llenar_f033(docx_bytes, items):
    doc = Document(io.BytesIO(docx_bytes))
    tabla = None
    for t in doc.tables:
        if len(t.columns) >= 6:
            tabla = t
            break

    if not tabla:
        raise Exception("No se encontro la tabla del F033 en el Word")

    filas_datos = []
    fila_total = None
    fila_template = None

    for row in tabla.rows:
        txt = row.cells[0].text.strip().lower()
        if any(k in txt for k in ['item', 'no.', 'descripci', 'unidad']):
            continue
        if 'valor total' in row.cells[0].text.lower():
            fila_total = row
            continue
        filas_datos.append(row)
        fila_template = row

    if len(filas_datos) < len(items):
        if fila_total and fila_template:
            faltan = len(items) - len(filas_datos)
            for _ in range(faltan):
                nueva_tr = deepcopy(fila_template._tr)
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                for tc in nueva_tr.findall(f'.//{ns}tc'):
                    for p in tc.findall(f'{ns}p'):
                        for r in p.findall(f'{ns}r'):
                            p.remove(r)
                fila_total._tr.addprevious(nueva_tr)
            filas_datos = []
            for row in tabla.rows:
                txt = row.cells[0].text.strip().lower()
                if any(k in txt for k in ['item', 'no.', 'descripci', 'unidad']):
                    continue
                if 'valor total' in row.cells[0].text.lower():
                    break
                filas_datos.append(row)
        else:
            while len(filas_datos) < len(items):
                filas_datos.append(tabla.add_row())

    for i, item in enumerate(items):
        if i >= len(filas_datos):
            break
        celdas = filas_datos[i].cells

        def set_cell(col, val, celdas=celdas):
            try:
                p = celdas[col].paragraphs[0]
                p.clear()
                run = p.add_run(str(val) if val is not None else '')
                run.font.size = Pt(9)
            except Exception as e:
                print(f"Error en celda {col}: {e}")

        lote = str(item.get('lote', '')).strip()
        num = item.get('numero', i + 1)
        etiqueta_num = f"L-{lote}-{num}" if lote else str(num)

        set_cell(0, etiqueta_num)
        set_cell(1, item.get('descripcion', ''))
        set_cell(2, item.get('unidad', ''))
        set_cell(3, item.get('cantidad', ''))

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output.getvalue()


@app.route('/agente-033', methods=['POST'])
def agente_033():
    try:
        data = request.get_json()
        referencia = data.get('referencia')

        if not referencia:
            return jsonify({"error": "Falta 'referencia'"}), 400

        print(f"\nAGENTE 033: {referencia}")
        nombre_seguro = re.sub(r'[^a-zA-Z0-9-]', '_', referencia)
        zip_path = f"{TEMP_DIR}/{nombre_seguro}.zip"

        print("PASO 1: Descargando ZIP...")
        os.makedirs(TEMP_DIR, exist_ok=True)

        zip_ya_existe = os.path.exists(zip_path) and \
            (time.time() - os.path.getmtime(zip_path)) / 86400 <= CACHE_DIAS

        if not zip_ya_existe:
            descargar_pliego(referencia, guardar_zip=True)
        else:
            print("ZIP en cache")

        if not os.path.exists(zip_path):
            return jsonify({"error": "No se pudo obtener el ZIP"}), 500

        print("PASO 2: Extrayendo archivos...")
        f033_bytes = None
        fichas_prioritarias = []
        fichas_pliego = []
        fichas_secundarias = []

        with zipfile.ZipFile(zip_path, 'r') as zf:
            for archivo in zf.namelist():
                if '1_Publicaciones/Adjuntos/' not in archivo:
                    continue
                nombre = os.path.basename(archivo).lower()

                if archivo.lower().endswith(('.docx', '.doc')):
                    if '033' in nombre:
                        f033_bytes = zf.read(archivo)
                        print(f"  F033 encontrado: {os.path.basename(archivo)}")

                if archivo.lower().endswith('.pdf'):
                    es_ficha = any(k in nombre for k in ['ficha', 'tecnica'])
                    es_pliego = any(k in nombre for k in ['pliego', 'condiciones', 'terminos'])
                    es_listado = any(k in nombre for k in ['listado', 'especificacion'])
                    if es_ficha:
                        fichas_prioritarias.append(zf.read(archivo))
                        print(f"  Ficha tecnica: {os.path.basename(archivo)}")
                    elif es_pliego:
                        fichas_pliego.append(zf.read(archivo))
                        print(f"  Pliego: {os.path.basename(archivo)}")
                    elif es_listado:
                        fichas_secundarias.append(zf.read(archivo))
                        print(f"  Listado: {os.path.basename(archivo)}")

        if not f033_bytes:
            return jsonify({
                "error": "No se encontro el F033 (.docx) en 1_Publicaciones/Adjuntos/. Esta licitacion puede ser Comparacion de Precios."
            }), 404

        # Construir candidatos en orden: pliego > ficha tecnica > listado
        candidatos = []
        if fichas_pliego:
            candidatos.append(('pliego', fichas_pliego))
        if fichas_prioritarias:
            candidatos.append(('ficha tecnica', fichas_prioritarias))
        if fichas_secundarias:
            candidatos.append(('listado', fichas_secundarias))

        if not candidatos:
            return jsonify({
                "error": "No es posible procesar el F033 porque no se encontraron PDFs con items en 1_Publicaciones/Adjuntos/."
            }), 404

        print(f"  F033 OK | Candidatos: {[c[0] for c in candidatos]}")

        # PASO 3: Intentar cada candidato hasta obtener suficientes items
        print("PASO 3: Extrayendo items con Claude...")
        items = []
        for nombre_candidato, fichas_bytes in candidatos:
            print(f"  Probando con: {nombre_candidato}")
            items = extraer_items_con_claude(fichas_bytes, referencia)
            print(f"  -> {len(items)} items encontrados")
            if len(items) >= 5:
                print(f"  Usando {nombre_candidato} ({len(items)} items)")
                break
            else:
                print(f"  Muy pocos items en {nombre_candidato}, probando siguiente...")

        if not items:
            return jsonify({"error": "Claude no extrajo items de ninguno de los PDFs disponibles"}), 500

        print("PASO 4: Generando F033 pre-llenado...")
        docx_relleno = llenar_f033(f033_bytes, items)
        print(f"  Word listo ({len(docx_relleno)} bytes)")

        return send_file(
            io.BytesIO(docx_relleno),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=f"F033_{nombre_seguro}.docx"
        )

    except Exception as e:
        print(f"Agente 033 error: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)