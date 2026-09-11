import os
import sys
import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ExtractorBrowserSeNaSA")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

def normalizar_texto(texto):
    if not texto:
        return ""
    return str(texto).strip()

def obtener_siguiente_id() -> int:
    try:
        res = supabase.table("vitalmi_directorio_master").select("id").order("id", desc=True).limit(1).execute()
        if res.data and len(res.data) > 0:
            val = res.data[0].get("id")
            if isinstance(val, int):
                return val + 1
    except Exception as e:
        logger.warning(f"⚠️ No se pudo obtener ID máximo: {e}")
    return 70000

def run_extraction():
    archivo_json = BASE_DIR / "medicos_senasa.json"
    todos_los_registros = []

    with sync_playwright() as p:
        # Abrimos el navegador en modo visible
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Interceptamos las peticiones de red para capturar el JSON cuando la app lo solicite
        def handle_response(response):
            if "/api/Prestador/todos" in response.url and response.status == 200:
                try:
                    data = response.json()
                    result = data.get("result", {})
                    data_list = result.get("data", [])
                    if data_list:
                        for item in data_list:
                            nombre = normalizar_texto(item.get("nombre"))
                            if nombre and not any(r.get("nombre") == nombre for r in todos_los_registros):
                                todos_los_registros.append(item)
                        logger.info(f"📥 Capturados vía red: {len(data_list)} registros | Acumulados totales: {len(todos_los_registros)}")
                except Exception as e:
                    pass

        page.on("response", handle_response)

        logger.info("🌐 Abriendo la sección de prestadores de SeNaSA...")
        # Apuntamos directamente a la dirección de prestadores
        page.goto("https://ova.arssenasa.gob.do/consulta/prestadores")

        logger.info("="*60)
        logger.info("💡 INSTRUCCIONES:")
        logger.info("1. Interactúa con la página de prestadores en el navegador abierto.")
        logger.info("2. Realiza las búsquedas o avanza por las páginas de la tabla.")
        logger.info("3. El script interceptará automáticamente las respuestas de la red.")
        logger.info("4. Presiona ENTER en esta terminal cuando termines de navegar para guardar y sincronizar.")
        logger.info("="*60)

        input("👉 Presiona [ENTER] en esta terminal una vez que hayas terminado de extraer/navegar...")

        browser.close()

    if not todos_los_registros:
        logger.warning("⚠️ No se capturaron registros durante la sesión del navegador.")
        return

    # Guardar en el archivo unificado medicos_senasa.json
    estructura_salida = {
        "resultType": 0,
        "result": {
            "cantidadRegistros": len(todos_los_registros),
            "data": todos_los_registros
        },
        "customErrorMessage": None,
        "mailRequest": None
    }

    with open(archivo_json, "w", encoding="utf-8") as f:
        json.dump(estructura_salida, f, ensure_ascii=False, indent=4)
    logger.info(f"💾 Archivo {archivo_json.name} actualizado con {len(todos_los_registros)} registros capturados.")

    sincronizar_con_supabase(todos_los_registros)

def sincronizar_con_supabase(lista_items):
    logger.info("🚀 Iniciando sincronización masiva a Supabase...")
    id_actual = obtener_siguiente_id()
    nuevos_registros = []

    for item in lista_items:
        nombre = normalizar_texto(item.get("nombre") or item.get("nombrePrestador") or item.get("razonSocial"))
        if not nombre:
            continue

        tipo_prestador_raw = str(item.get("tipoPrestador", "")).lower()
        is_centro = "centro" in tipo_prestador_raw or "clinica" in tipo_prestador_raw or "hospital" in tipo_prestador_raw
        
        tipo_p = "CENTRO_MEDICO" if is_centro else "MEDICO"
        especialidad = normalizar_texto(item.get("especialidad") or ("Clínica Privada" if is_centro else "Medicina General"))
        direccion = normalizar_texto(item.get("direccion") or "República Dominicana")
        municipio = normalizar_texto(item.get("municipio") or item.get("nombreMunicipio") or "República Dominicana")
        telefono = normalizar_texto(item.get("telefono") or item.get("telefono1") or "No disponible")

        doc = {
            "id": id_actual,
            "nombre": nombre,
            "tipo_prestador": tipo_p,
            "especialidad": especialidad,
            "centro_medico": "Ejercicio Independiente" if tipo_p == "MEDICO" else nombre,
            "direccion": direccion,
            "provincia": municipio,
            "telefono_institucional": telefono,
            "whatsapp": telefono,
            "aseguradoras": ["SeNaSA"],
            "embedding": None
        }

        nuevos_registros.append(doc)
        id_actual += 1

    tamanio_lote = 100
    insertados_total = 0

    for i in range(0, len(nuevos_registros), tamanio_lote):
        lote = nuevos_registros[i:i + tamanio_lote]
        try:
            supabase.table("vitalmi_directorio_master").upsert(lote).execute()
            insertados_total += len(lote)
            logger.info(f"   • Lote enviado a Supabase: {insertados_total}/{len(nuevos_registros)}...")
        except Exception as e:
            logger.error(f"❌ Error al insertar lote en Supabase: {e}")

    logger.info("="*50)
    logger.info(f"🎉 ¡PROCESO COMPLETADO EXITOSAMENTE!")
    logger.info(f"   • Total de registros sincronizados: {insertados_total}")
    logger.info("="*50)

if __name__ == "__main__":
    run_extraction()