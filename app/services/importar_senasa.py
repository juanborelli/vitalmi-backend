import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ImportadorSeNaSA")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

URL_API_SENASA = "https://apiova.arssenasa.gob.do/api/Prestador/todos"

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
    return 60000

def extraer_todo_senasa(token_bearer: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Authorization": f"Bearer {token_bearer}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://ova.arssenasa.gob.do",
        "Referer": "https://ova.arssenasa.gob.do/"
    }

    archivo_json = BASE_DIR / "prestadores_senasa.json"
    todos_los_prestadores = []
    pagina = 1
    registros_por_pagina = 500  # Pide en bloques de 500 registros

    logger.info("🚀 Iniciando extracción masiva desde la API de SeNaSA...")

    while True:
        payload = {
            "IdPrestador": 0,
            "IdTipoCentro": 0,
            "Nombre": "",
            "IdEspecialidad": 0,
            "IdPlan": 0,
            "IdRegimen": 0,
            "IdMunicipio": 0,
            "IdProvincia": 0,
            "NumeroDePagina": pagina,
            "RegistrosPorPagina": registros_por_pagina
        }

        try:
            res = requests.post(URL_API_SENASA, json=payload, headers=headers, timeout=15)
            if res.status_code != 200:
                logger.error(f"❌ Error HTTP {res.status_code}: {res.text}")
                break

            response_json = res.json()
            result_obj = response_json.get("result", {})
            data_list = result_obj.get("data", [])

            if not data_list:
                logger.info("✅ No hay más registros devueltos. Extracción finalizada.")
                break

            todos_los_prestadores.extend(data_list)
            logger.info(f" 📦 Página {pagina} procesada | Acumulado: {len(todos_los_prestadores)} / {result_obj.get('cantidadRegistros', '?')}")

            if len(data_list) < registros_por_pagina:
                break

            pagina += 1
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"❌ Excepción durante la llamada HTTP: {e}")
            break

    logger.info(f" Total general extraído de SeNaSA: {len(todos_los_prestadores)} registros.")

    # Guardar respaldo local
    with open(archivo_json, "w", encoding="utf-8") as f:
        json.dump(todos_los_prestadores, f, ensure_ascii=False, indent=4)
    logger.info(f"💾 Respaldo guardado en {archivo_json.name}")

    if todos_los_prestadores:
        importar_senasa_a_supabase(todos_los_prestadores)

def importar_senasa_a_supabase(lista_prestadores):
    logger.info("🔍 Consultando catálogo existente en Supabase...")
    res_actuales = supabase.table("vitalmi_directorio_master").select("id, nombre, aseguradoras").execute()
    existentes = res_actuales.data or []
    
    id_actual = obtener_siguiente_id()
    mapa_existentes = {normalizar_texto(item['nombre']).lower(): item for item in existentes}

    nuevos = 0
    actualizados = 0

    for item in lista_prestadores:
        nombre = normalizar_texto(item.get("nombre"))
        if not nombre:
            continue

        especialidad_raw = normalizar_texto(item.get("especialidad") or "General").upper()
        tipo_prestador_raw = normalizar_texto(item.get("tipoPrestador") or "CENTRO").upper()

        if "FARMACIA" in especialidad_raw or "FARMACEUTICO" in especialidad_raw:
            tipo_prestador = "FARMACIA"
        elif "LABORATORIO" in especialidad_raw:
            tipo_prestador = "LABORATORIO"
        elif any(k in especialidad_raw for k in ["CLINICA", "HOSPITAL", "CENTRO", "ODONTOLOGICO", "SALUD MENTAL", "REHABILITACION"]):
            tipo_prestador = "CLINICA"
        elif "MEDICO" in tipo_prestador_raw:
            tipo_prestador = "MEDICO"
        else:
            tipo_prestador = "CLINICA"

        telefono_raw = normalizar_texto(item.get("telefono")) or "No disponible"
        direccion_raw = normalizar_texto(item.get("direccion")) or "República Dominicana"
        municipio_raw = normalizar_texto(item.get("municipio")) or "República Dominicana"

        doc = {
            "nombre": nombre,
            "tipo_prestador": tipo_prestador,
            "especialidad": item.get("especialidad") or "General",
            "centro_medico": "No especificado",
            "direccion": direccion_raw,
            "provincia": municipio_raw,
            "telefono_institucional": telefono_raw,
            "whatsapp": telefono_raw,
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
    logger.info(f"🎉 IMPORTACIÓN DE SENASA COMPLETADA:")
    logger.info(f"   • Nuevos registros insertados: {nuevos}")
    logger.info(f"   • Registros actualizados con 'SeNaSA': {actualizados}")
    logger.info("="*50)

if __name__ == "__main__":
    TOKEN_BEARER = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJlYWViNzE1MC02OGU1LTQ0NWUtOGI3Mi0zOTU4MDlhYzQ4NTkiLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL3JvbGUiOlsiQ09OU19NRU5VIiwiQ09OU19QUk9WSU5DSUFTIiwiQ09OU19NVU5JQ0lQSU9TIiwiQ09OU19SRUdJTUVORVMiLCJDT05TX0dSVVBPX1BEU1MiLCJDT05TX1NVQl9HUlVQT19QRFNTIiwiQ09OU19QUk9DRURJTUlFTlRPUyIsIkNPTlNfQ09CRVJUVVJBX1BST0NFRElNSUVOVE8iLCJDT05TX0VTUEVDSUFMSURBRCIsIkNPTlNfVElQT19QUkVTVEFET1JFUyIsIkNPTlNfUFJFU1RBRE9SRVMiLCJDT05TX0RFVEFMTEVfUFJFU1RBRE9SRVMiLCJDT05TX1JFR0lNRU4iLCJHRVRfTk9USUZJQ0FDSU9ORVMiXSwiZXhwIjoxNzg4NzQxNjQ3LCJpc3MiOiJodHRwczovL2FwaW92YS5hcnNzZW5hc2EuZ29iLmRvLyIsImF1ZCI6IlVzZXIifQ.4OU3hpQUD7UG2NlukdtcaXsfopj16M--7KiJjgJNabM"
    
    extraer_todo_senasa(TOKEN_BEARER)