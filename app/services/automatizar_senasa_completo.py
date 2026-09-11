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
logger = logging.getLogger("AutomatizadorSeNaSACompleto")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

URL_TODOS = "https://apiova.arssenasa.gob.do/api/Prestador/todos"

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

def extraer_y_sostener(token_bearer: str):
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "es,es-419;q=0.9,en;q=0.8",
        "authorization": f"Bearer {token_bearer}",
        "content-type": "application/json",
        "origin": "https://ova.arssenasa.gob.do",
        "referer": "https://ova.arssenasa.gob.do/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    }

    # Pedimos bloques grandes de 500 o 1000 registros por página
    registros_por_pagina = 500 
    pagina = 1
    total_registros_api = None
    todos_los_registros = []

    logger.info("🚀 Iniciando extracción automatizada masiva de SeNaSA...")

    while True:
        payload = {
            "IdPrestador": 0,
            "IdTipoCentro": 1,  # 1 para médicos
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
            res = requests.post(URL_TODOS, json=payload, headers=headers, timeout=20, verify=False)
            
            if res.status_code == 401:
                logger.error("❌ Token Bearer expirado (HTTP 401). Actualiza el token en el script.")
                break
            elif res.status_code != 200:
                logger.error(f"❌ Error HTTP {res.status_code}: {res.text}")
                break

            body = res.json()
            result = body.get("result", {})
            
            if total_registros_api is None:
                total_registros_api = result.get("cantidadRegistros", 0)
                logger.info(f"📊 Total absoluto reportado por SeNaSA: {total_registros_api} registros.")

            data_list = result.get("data", [])
            if not data_list:
                break

            todos_los_registros.extend(data_list)
            logger.info(f"📄 Página {pagina} descargada (+{len(data_list)} registros) | Acumulados: {len(todos_los_registros)}/{total_registros_api}")

            if len(todos_los_registros) >= total_registros_api or len(data_list) < registros_por_pagina:
                break

            pagina += 1
            time.sleep(0.2) # Pausa breve para estabilidad de red

        except Exception as e:
            logger.error(f"❌ Excepción de red en página {pagina}: {e}")
            break

    if not todos_los_registros:
        logger.warning("⚠️ No se obtuvieron registros.")
        return

    # Guardamos el resultado completo en el archivo unificado medicos_senasa.json
    archivo_json = BASE_DIR / "medicos_senasa.json"
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
    logger.info(f"💾 Archivo unificado {archivo_json.name} actualizado con {len(todos_los_registros)} registros.")

    # Ahora procedemos a cargarlo masivamente a Supabase
    sincronizar_con_supabase(todos_los_registros)

def sincronizar_con_supabase(lista_items):
    logger.info("🚀 Preparando importación masiva a Supabase...")
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

    # Inserción masiva en lotes de 100 para Supabase
    tamanio_lote = 100
    insertados_total = 0

    for i in range(0, len(nuevos_registros), tamanio_lote):
        lote = nuevos_registros[i:i + tamanio_lote]
        try:
            supabase.table("vitalmi_directorio_master").upsert(lote).execute()
            insertados_total += len(lote)
            logger.info(f"   • Lote enviado a Supabase: {insertados_total}/{len(nuevos_registros)} procesados...")
        except Exception as e:
            logger.error(f"❌ Error al insertar lote en Supabase: {e}")

    logger.info("="*50)
    logger.info(f"🎉 EXTRACCIÓN Y CARGA MASIVA COMPLETADA EXITOSAMENTE:")
    logger.info(f"   • Total de registros procesados: {insertados_total}")
    logger.info("="*50)

if __name__ == "__main__":
    # Pega aquí tu token Bearer más reciente con permisos para /Prestador/todos
    TOKEN_BEARER = "TU_TOKEN_BEARER_AQUI"
    extraer_y_sostener(TOKEN_BEARER)