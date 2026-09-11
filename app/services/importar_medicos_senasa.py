import os
import sys
import json
import time
import logging
import requests
import urllib3
from pathlib import Path
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ImportadorDetalleSeNaSA")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

URL_DETALLE = "https://apiova.arssenasa.gob.do/api/Prestador/detalle"

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

def extraer_por_detalle_secuencial(token_bearer: str, id_inicio: int = 1, id_fin: int = 45000):
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "es,es-419;q=0.9,en;q=0.8",
        "authorization": f"Bearer {token_bearer}",
        "origin": "https://ova.arssenasa.gob.do",
        "referer": "https://ova.arssenasa.gob.do/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    }

    archivo_json = BASE_DIR / "medicos_senasa.json"
    medicos_extraidos = []

    logger.info(f"🚀 Iniciando barrido secuencial por detalle (IDs {id_inicio} al {id_fin})...")

    for id_p in range(id_inicio, id_fin + 1):
        params = {
            "idPrestador": id_p,
            "TipoPrestador": 1
        }

        try:
            res = requests.get(URL_DETALLE, params=params, headers=headers, timeout=5, verify=False)
            
            if res.status_code == 200:
                body = res.json()
                result = body.get("result")
                if result:
                    items = result if isinstance(result, list) else [result]
                    for item in items:
                        if item and item.get("nombre"):
                            medicos_extraidos.append(item)
                            logger.info(f" 🩺 [ID {id_p}] Encontrado: {item.get('nombre')} | {item.get('especialidad')}")
            elif res.status_code == 401:
                logger.error("❌ Token Bearer expirado (HTTP 401). Deteniendo barrido.")
                break
        except Exception:
            pass

        if id_p % 200 == 0:
            logger.info(f"📊 Progreso actual: ID {id_p}/{id_fin} | Acumulados: {len(medicos_extraidos)}")
            # Guardado temporal de respaldo cada 200 IDs
            with open(archivo_json, "w", encoding="utf-8") as f:
                json.dump(medicos_extraidos, f, ensure_ascii=False, indent=4)

        time.sleep(0.05) # Pequeña pausa para estabilidad

    logger.info(f"✅ Barrido finalizado. Total de médicos recolectados: {len(medicos_extraidos)}")

    if medicos_extraidos:
        with open(archivo_json, "w", encoding="utf-8") as f:
            json.dump(medicos_extraidos, f, ensure_ascii=False, indent=4)
        importar_medicos_a_supabase(medicos_extraidos)

def importar_medicos_a_supabase(lista_medicos):
    logger.info("🔍 Deduplicando e importando registros en Supabase...")
    res_actuales = supabase.table("vitalmi_directorio_master").select("id, nombre, aseguradoras").eq("tipo_prestador", "MEDICO").execute()
    existentes = res_actuales.data or []
    
    id_actual = obtener_siguiente_id()
    mapa_existentes = {normalizar_texto(item['nombre']).lower(): item for item in existentes}

    nuevos = 0
    actualizados = 0

    for item in lista_medicos:
        nombre = normalizar_texto(item.get("nombre"))
        if not nombre:
            continue

        doc = {
            "nombre": nombre,
            "tipo_prestador": "MEDICO",
            "especialidad": normalizar_texto(item.get("especialidad") or "Medicina General"),
            "centro_medico": "Ejercicio Independiente",
            "direccion": normalizar_texto(item.get("direccion") or "República Dominicana"),
            "provincia": normalizar_texto(item.get("municipio") or "República Dominicana"),
            "telefono_institucional": normalizar_texto(item.get("telefono") or "No disponible"),
            "whatsapp": normalizar_texto(item.get("telefono") or "No disponible"),
            "aseguradoras": ["SeNaSA"],
            "embedding": None
        }

        clave = nombre.lower()

        if clave in mapa_existentes:
            item_existente = mapa_existentes[clave]
            aseguradoras = item_existente.get("aseguradoras") or []
            if isinstance(aseguradoras, str):
                aseguradoras = [aseguradoras]

            if "SeNaSA" not in aseguradoras:
                aseguradoras.append("SeNaSA")
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
    logger.info(f"🎉 IMPORTACIÓN COMPLETADA EN SUPABASE:")
    logger.info(f"   • Nuevos médicos insertados: {nuevos}")
    logger.info(f"   • Médicos existentes actualizados con 'SeNaSA': {actualizados}")
    logger.info("="*50)

if __name__ == "__main__":
    TOKEN_BEARER = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJiYzMxNTVlMy1lMzg0LTQ5ZjYtYmNkMy05MzQyZGZkZjQ5ZmIiLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL3JvbGUiOlsiQ09OU19NRU5VIiwiQ09OU19QUk9WSU5DSUFTIiwiQ09OU19NVU5JQ0lQSU9TIiwiQ09OU19SRUdJTUVORVMiLCJDT05TX0dSVVBPX1BEU1MiLCJDT05TX1NVQl9HUlVQT19QRFNTIiwiQ09OU19QUk9DRURJTUlFTlRPUyIsIkNPTlNfQ09CRVJUVVJBX1BST0NFRElNSUVOVE8iLCJDT05TX1VTUEVDSUFMSURBRCIsIkNPTlNfVElQT19QUkVTVEFET1JFUyIsIkNPTlNfUFJFU1RBRE9SRVMiLCJDT05TX1RFVEFMTEVfUFJFU1RBRE9SRVMiLCJDT05TX1JFR0lNRU4iLCJHRVRfTk9USUZJQ0FDSU9ORVMiXSwiZXhwIjoxNzg4NzQ0MzMwLCJpc3MiOiJodHRwczovL2FwaW92YS5hcnNzZW5hc2EuZ29iLmRvLyIsImF1ZCI6IlVzZXIifQ.88_T0xiFW0S3E_bG3YFL4zyH7f5O-Bzjwxy4vHqCPvg"
    
    # Ejecuta el escaneo secuencial robusto
    extraer_por_detalle_secuencial(TOKEN_BEARER, id_inicio=1, id_fin=45000)