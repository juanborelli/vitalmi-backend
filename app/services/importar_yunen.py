import os
import sys
import pandas as pd
import logging
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ImportadorYunen")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

def normalizar_texto(texto):
    if pd.isna(texto) or not texto:
        return ""
    return str(texto).strip()

def procesar_excel_yunen(ruta_excel: Path):
    if not ruta_excel.exists():
        logger.error(f"❌ No se encontró el archivo Excel en: {ruta_excel}")
        return

    logger.info(f"📂 Cargando archivo Excel: {ruta_excel.name}")
    df = pd.read_excel(ruta_excel)
    
    logger.info("🔍 Obteniendo catálogo existente desde Supabase...")
    res_actuales = supabase.table("vitalmi_directorio_master").select("id, nombre, provincia, aseguradoras").execute()
    existentes = res_actuales.data or []
    
    # Determinar el último ID utilizado para autoincrementar si es necesario
    max_id = max([item['id'] for item in existentes if isinstance(item.get('id'), int)], default=0)
    logger.info(f"📌 Último ID registrado en Supabase: {max_id}")

    mapa_existentes = {}
    for item in existentes:
        clave = f"{normalizar_texto(item['nombre']).lower()}_{normalizar_texto(item['provincia']).lower()}"
        mapa_existentes[clave] = item

    nuevos_registros = 0
    actualizados = 0

    logger.info("⚡ Procesando y cruzando filas del Excel...")

    for idx, row in df.iterrows():
        nombre = normalizar_texto(row.get("NOMBRE") or row.get("Nombre") or row.get("Medico") or row.get("Razon Social"))
        if not nombre:
            continue

        especialidad = normalizar_texto(row.get("ESPECIALIDAD") or row.get("Especialidad") or "General")
        centro = normalizar_texto(row.get("CENTRO_MEDICO") or row.get("Centro") or row.get("Consultorio") or "")
        direccion = normalizar_texto(row.get("DIRECCION") or row.get("Direccion") or "")
        provincia = normalizar_texto(row.get("PROVINCIA") or row.get("Provincia") or "")
        municipio = normalizar_texto(row.get("MUNICIPIO") or row.get("Municipio") or "")
        telefono = normalizar_texto(row.get("TELEFONO") or row.get("Telefono") or row.get("Celular") or "")
        
        clave_busqueda = f"{nombre.lower()}_{provincia.lower()}"

        if clave_busqueda in mapa_existentes:
            item_existente = mapa_existentes[clave_busqueda]
            aseguradoras_actuales = item_existente.get("aseguradoras") or []
            if isinstance(aseguradoras_actuales, str):
                aseguradoras_actuales = [aseguradoras_actuales]

            if "ARS Yunen" not in aseguradoras_actuales:
                aseguradoras_actuales.append("ARS Yunen")
                supabase.table("vitalmi_directorio_master").update({
                    "aseguradoras": aseguradoras_actuales,
                    "embedding": None
                }).eq("id", item_existente["id"]).execute()
                actualizados += 1
        else:
            max_id += 1  # Asignar el siguiente ID válido
            nuevo_doc = {
                "id": max_id,
                "nombre": nombre,
                "tipo_prestador": "MEDICO",
                "especialidad": especialidad,
                "centro_medico": centro,
                "direccion": direccion,
                "provincia": provincia,
                "municipio_cabecera": municipio,
                "telefono_institucional": telefono,
                "whatsapp": telefono,
                "aseguradoras": ["ARS Yunen"],
                "embedding": None
            }
            supabase.table("vitalmi_directorio_master").insert(nuevo_doc).execute()
            nuevos_registros += 1

        if (idx + 1) % 100 == 0:
            logger.info(f"   • Procesadas {idx + 1}/{len(df)} filas...")

    logger.info("="*50)
    logger.info(f"🎉 IMPORTACIÓN COMPLETA DE ARS YUNEN:")
    logger.info(f"   • Médicos nuevos insertados: {nuevos_registros}")
    logger.info(f"   • Médicos existentes actualizados con 'ARS Yunen': {actualizados}")
    logger.info("="*50)

if __name__ == "__main__":
    archivo_excel = BASE_DIR / "ProveedoresMedicosYunen.xlsx"
    procesar_excel_yunen(archivo_excel)