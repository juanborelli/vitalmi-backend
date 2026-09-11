import os
import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ImportadorDirectorioMasivo")

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

def importar_archivo_json(nombre_archivo: str = "medicos_senasa.json"):
    archivo_json = BASE_DIR / nombre_archivo
    
    if not archivo_json.exists():
        logger.error(f"❌ No se encontró el archivo {archivo_json.name} en la raíz.")
        return

    logger.info(f"📂 Leyendo archivo local: {archivo_json.name}")
    
    try:
        texto_crudo = archivo_json.read_text(encoding="utf-8", errors="ignore")
        contenido = json.loads(texto_crudo)
    except Exception as e:
        logger.error(f"❌ Error al leer el JSON: {e}")
        return

    lista_items = []
    if isinstance(contenido, list):
        lista_items = contenido
    elif isinstance(contenido, dict):
        result_obj = contenido.get("result")
        if isinstance(result_obj, list):
            lista_items = result_obj
        elif isinstance(result_obj, dict):
            if "data" in result_obj:
                lista_items = result_obj.get("data", [])
            else:
                lista_items = [result_obj]
        else:
            lista_items = [contenido]

    logger.info(f"   • Total de registros leídos en archivo: {len(lista_items)}")

    # Preparamos los documentos en memoria sin saturar Supabase con consultas individuales
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

    if not nuevos_registros:
        logger.info("⚠️ No hay registros válidos para insertar.")
        return

    logger.info(f"🚀 Insertando lote de {len(nuevos_registros)} registros en Supabase (modo masivo)...")

    # Inserción por lotes (chunks de 50 para evitar límites de payload)
    tamanio_lote = 50
    insertados_total = 0

    for i in range(0, len(nuevos_registros), tamanio_lote):
        lote = nuevos_registros[i:i + tamanio_lote]
        try:
            # Usamos upsert para evitar conflictos si algún ID ya existiera de antemano
            supabase.table("vitalmi_directorio_master").upsert(lote).execute()
            insertados_total += len(lote)
            logger.info(f"   • Lote enviado: {insertados_total}/{len(nuevos_registros)} procesados...")
        except Exception as e:
            logger.error(f"❌ Error al insertar el lote en Supabase: {e}")

    logger.info("="*50)
    logger.info(f"🎉 IMPORTACIÓN MASIVA FINALIZADA:")
    logger.info(f"   • Total de registros enviados a Supabase: {insertados_total}")
    logger.info("="*50)

if __name__ == "__main__":
    archivo_a_procesar = sys.argv[1] if len(sys.argv) > 1 else "medicos_senasa.json"
    importar_archivo_json(archivo_a_procesar)