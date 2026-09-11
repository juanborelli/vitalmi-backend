import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

# Configurar directorio raíz del proyecto (VitalMi-backend)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

# Configuración de Logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ImportadorMapfre")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

URL_MAPFRE_BASE = "https://servicios.mapfresaludars.com.do/providerInfo/2/"

def consultar_api_mapfre(provider_id: int) -> dict:
    url = f"{URL_MAPFRE_BASE}{provider_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and data.get("name"):
                return data
    except Exception as e:
        logger.warning(f"⚠️ Error consultando ID {provider_id} en Mapfre: {e}")
    
    return None

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
    return 30000

def ejecutar_extraccion_mapfre(rango_inicio: int, rango_fin: int):
    archivo_json = BASE_DIR / "farmacias_mapfre.json"
    
    farmacias_mapfre = {}
    if archivo_json.exists():
        try:
            with open(archivo_json, "r", encoding="utf-8") as f:
                datos_previos = json.load(f)
                for p in datos_previos:
                    if p.get("name"):
                        farmacias_mapfre[p.get("name")] = p
            logger.info(f"📂 Cargadas {len(farmacias_mapfre)} farmacias previas de Mapfre.")
        except Exception:
            pass

    logger.info(f"🚀 Iniciando extracción de Mapfre Salud (IDs {rango_inicio} a {rango_fin})...")

    for provider_id in range(rango_inicio, rango_fin + 1):
        data = consultar_api_mapfre(provider_id)
        if data:
            nombre = normalizar_texto(data.get("name"))
            if nombre and nombre not in farmacias_mapfre:
                farmacias_mapfre[nombre] = data
                logger.info(f" ✅ [ID {provider_id}] Farmacia Mapfre: {nombre}")

                if len(farmacias_mapfre) % 10 == 0:
                    with open(archivo_json, "w", encoding="utf-8") as f:
                        json.dump(list(farmacias_mapfre.values()), f, ensure_ascii=False, indent=4)

        time.sleep(0.05)

    lista_final = list(farmacias_mapfre.values())
    with open(archivo_json, "w", encoding="utf-8") as f:
        json.dump(lista_final, f, ensure_ascii=False, indent=4)

    logger.info(f"💾 Total capturado de Mapfre guardado en JSON: {len(lista_final)}")
    importar_mapfre_a_supabase(lista_final)

def importar_mapfre_a_supabase(lista_farmacias: list):
    logger.info("🔍 Obteniendo catálogo existente desde Supabase...")
    res_actuales = supabase.table("vitalmi_directorio_master").select("id, nombre, provincia, aseguradoras").execute()
    existentes = res_actuales.data or []
    
    id_actual = obtener_siguiente_id()
    mapa_existentes = {normalizar_texto(item['nombre']).lower(): item for item in existentes}

    nuevos_registros = 0
    actualizados = 0

    for item in lista_farmacias:
        nombre = normalizar_texto(item.get("name"))
        if not nombre:
            continue

        direccion = normalizar_texto(item.get("address"))
        phones = item.get("phoneNumbers", [])
        telefono = normalizar_texto(phones[0].get("value")) if phones else "No disponible"
        ciudad = normalizar_texto(item.get("city")) or "República Dominicana"

        doc_farmacia = {
            "nombre": nombre,
            "tipo_prestador": "FARMACIA",
            "especialidad": "General",
            "centro_medico": "No especificado",
            "direccion": direccion,
            "provincia": ciudad,
            "telefono_institucional": telefono,
            "whatsapp": telefono,
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
            doc_farmacia["id"] = id_actual
            id_actual += 1
            supabase.table("vitalmi_directorio_master").insert(doc_farmacia).execute()
            nuevos_registros += 1

    logger.info("="*50)
    logger.info(f"🎉 IMPORTACIÓN DE MAPFRE SALUD COMPLETADA:")
    logger.info(f"   • Nuevas farmacias insertadas: {nuevos_registros}")
    logger.info(f"   • Farmacias cruzadas actualizadas con 'Mapfre Salud ARS': {actualizados}")
    logger.info("="*50)

if __name__ == "__main__":
    # Rango alrededor del ID de 2B FARMA (8277563)
    ejecutar_extraccion_mapfre(rango_inicio=8270000, rango_fin=8280000)