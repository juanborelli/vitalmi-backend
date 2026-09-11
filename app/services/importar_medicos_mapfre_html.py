import os
import sys
import json
import logging
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ImportadorMedicosMapfre")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

URL_DIRECTORIO = "https://servicios.mapfresaludars.com.do/directorio-medico"

def normalizar_texto(texto):
    if not texto:
        return ""
    return str(texto).strip()

def obtener_siguiente_id() -> int:
    """Obtiene el ID máximo actual en Supabase para evitar el error de clave duplicada"""
    try:
        res = supabase.table("vitalmi_directorio_master").select("id").order("id", desc=True).limit(1).execute()
        if res.data and len(res.data) > 0:
            val = res.data[0].get("id")
            if isinstance(val, int):
                return val + 1
    except Exception as e:
        logger.warning(f"⚠️ No se pudo obtener el ID máximo: {e}")
    return 50000  # Offset de reserva elevado para evitar colisiones

def extraer_e_importar_medicos_mapfre():
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": URL_DIRECTORIO
    }

    # 1. Obtener Token CSRF y Cookie de sesión
    logger.info("🌐 Obteniendo token CSRF de Mapfre Salud...")
    try:
        resp_get = session.get(URL_DIRECTORIO, headers=headers, timeout=15)
        if resp_get.status_code != 200:
            logger.error(f"❌ Error al cargar directorio inicial: HTTP {resp_get.status_code}")
            return

        soup_get = BeautifulSoup(resp_get.text, "html.parser")
        token_input = soup_get.find("input", {"name": "_token"})
        token = token_input.get("value") if token_input else ""

        logger.info("🔑 Token obtenido con éxito.")
    except Exception as e:
        logger.error(f"❌ Error al conectar con Mapfre: {e}")
        return

    # 2. Petición POST con type=99 (Médicos)
    logger.info("🌐 Solicitando listado completo de Médicos a Mapfre Salud ARS...")
    payload = {
        "_token": token,
        "planId": "",
        "cityId": "0",
        "type": "99",  # 99 = Médicos
        "specialty": "0"
    }

    try:
        response = session.post(URL_DIRECTORIO, data=payload, headers=headers, timeout=25)
        if response.status_code != 200:
            logger.error(f"❌ Error en consulta POST: HTTP {response.status_code}")
            return
            
        html_content = response.text
    except Exception as e:
        logger.error(f"❌ Falla de red: {e}")
        return

    # 3. Parsear el HTML
    logger.info("🔍 Extrayendo registros médicos de la tabla HTML...")
    soup = BeautifulSoup(html_content, "html.parser")
    filas = soup.find_all("tr")
    
    medicos_extraidos = []

    for fila in filas:
        a_tag = fila.find("a", class_="modal-triger")
        if not a_tag:
            continue

        nombre = normalizar_texto(a_tag.text)
        detail_path = a_tag.get("data-detailpath", "")
        
        modal_id = a_tag.get("data-bs-target", "").replace("#", "")
        modal = soup.find("div", id=modal_id)
        
        especialidad = "Medicina General"
        telefonos = []

        if modal:
            esp_span = modal.find("span", class_="specialtyList")
            if esp_span and esp_span.text.strip():
                especialidad = normalizar_texto(esp_span.text)

            lis = modal.find_all("li")
            for li in lis:
                txt = li.text.strip()
                if any(k in txt for k in ["DIRECTO:", "TRABAJO:", "CELULAR:", "RESIDENCIA:", "CLINICA CENTRAL:"]):
                    telefonos.append(txt)

        telefono_str = ", ".join(telefonos) if telefonos else "No disponible"

        medicos_extraidos.append({
            "nombre": nombre,
            "especialidad": especialidad,
            "detail_path": detail_path,
            "telefono": telefono_str
        })

    logger.info(f" Total de médicos parseados: {len(medicos_extraidos)}")

    if not medicos_extraidos:
        logger.warning("⚠️ No se obtuvieron médicos en el parseo.")
        return

    # Guardar respaldo local
    archivo_json = BASE_DIR / "medicos_mapfre.json"
    with open(archivo_json, "w", encoding="utf-8") as f:
        json.dump(medicos_extraidos, f, ensure_ascii=False, indent=4)
    logger.info(f"💾 Respaldo guardado en {archivo_json.name}")

    # Importar a Supabase
    importar_medicos_a_supabase(medicos_extraidos)

def importar_medicos_a_supabase(lista_medicos):
    logger.info("🔍 Verificando médicos existentes en Supabase...")
    res_actuales = supabase.table("vitalmi_directorio_master").select("id, nombre, aseguradoras").eq("tipo_prestador", "MEDICO").execute()
    existentes = res_actuales.data or []
    
    id_actual = obtener_siguiente_id()
    logger.info(f"📌 Próximo ID asignable dinámico: {id_actual}")
    
    mapa_existentes = {normalizar_texto(item['nombre']).lower(): item for item in existentes}

    nuevos = 0
    actualizados = 0

    for item in lista_medicos:
        nombre = item["nombre"]
        if not nombre:
            continue

        doc = {
            "nombre": nombre,
            "tipo_prestador": "MEDICO",
            "especialidad": item["especialidad"],
            "centro_medico": "No especificado",
            "direccion": "República Dominicana",
            "provincia": "República Dominicana",
            "telefono_institucional": item["telefono"],
            "whatsapp": item["telefono"],
            "aseguradoras": ["Mapfre Salud ARS"],
            "embedding": None
        }

        clave = nombre.lower()

        if clave in mapa_existentes:
            item_existente = mapa_existentes[clave]
            aseguradoras = item_existente.get("aseguradoras") or []
            if isinstance(aseguradoras, str):
                aseguradoras = [aseguradoras]

            if "Mapfre Salud ARS" not in aseguradoras:
                aseguradoras.append("Mapfre Salud ARS")
                supabase.table("vitalmi_directorio_master").update({
                    "aseguradoras": aseguradoras,
                    "embedding": None
                }).eq("id", item_existente["id"]).execute()
                actualizados += 1
        else:
            doc["id"] = id_actual
            id_actual += 1
            supabase.table("vitalmi_directorio_master").insert(doc).execute()
            nuevos += 1

    logger.info("="*50)
    logger.info(f"🎉 IMPORTACIÓN DE MÉDICOS DE MAPFRE COMPLETADA:")
    logger.info(f"   • Nuevos médicos insertados: {nuevos}")
    logger.info(f"   • Médicos cruzados actualizados con 'Mapfre Salud ARS': {actualizados}")
    logger.info("="*50)

if __name__ == "__main__":
    extraer_e_importar_medicos_mapfre()