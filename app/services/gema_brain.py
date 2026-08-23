import os
import re
from typing import Dict, List, Any
from dotenv import load_dotenv
from app.core.supabase import obtener_cliente_supabase

load_dotenv(override=True)
supabase = obtener_cliente_supabase()

# Diccionario de raíces de búsqueda para especialidades comunes
MAPEO_RAICES_ESPECIALIDAD = {
    "ginecologia": "GINEC",
    "ginecologo": "GINEC",
    "ginecologa": "GINEC",
    "obstetricia": "OBSTETR",
    "ginecologia y obstetricia": "GINEC",
    "cardiologia": "CARDIO",
    "cardiologo": "CARDIO",
    "pediatria": "PEDIAT",
    "pediatra": "PEDIAT",
    "dermatologia": "DERMAT",
    "dermatologo": "DERMAT",
    "ortopedia": "ORTOP",
    "traumatologia": "TRAUMAT",
    "oftalmologia": "OFTALM",
    "neurologia": "NEUROL",
    "odontologia": "ODONT"
}

def obtener_raiz_especialidad(especialidad_input: str) -> str:
    """Retorna la raíz óptima de búsqueda o la cadena limpia en mayúsculas."""
    clean = (especialidad_input or "").strip().lower()
    if clean in MAPEO_RAICES_ESPECIALIDAD:
        return MAPEO_RAICES_ESPECIALIDAD[clean]
    # Si no está en el mapa, toma los primeros 5 caracteres o la palabra completa en mayúsculas
    return clean[:5].upper() if len(clean) >= 5 else clean.upper()

def consultar_directorio_master(
    especialidad: str, 
    provincia: str = None, 
    municipio_cabecera: str = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Realiza una búsqueda precisa y flexible en 'vitalmi_directorio_master'
    evaluando simultáneamente 'especialidad', 'especialidad_medico' y 'especialidad_clinica'.
    """
    if not supabase:
        return {"status": "error", "message": "Conexión a Supabase no disponible", "data": []}

    raiz_esp = obtener_raiz_especialidad(especialidad)
    pattern = f"%{raiz_esp}%"

    # Construir la consulta a Supabase
    query = supabase.table("vitalmi_directorio_master").select(
        "id, nombre, tipo_prestador, especialidad, especialidad_medico, "
        "centro_medico, direccion, provincia, municipio_cabecera, sector, "
        "telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
    )

    # Filtro multi-columna para capturar cualquier variación de la especialidad
    query = query.or_(
        f"especialidad.ilike.{pattern},"
        f"especialidad_medico.ilike.{pattern},"
        f"especialidad_clinica.ilike.{pattern}"
    )

    # Filtros geográficos opcionales
    if provincia:
        query = query.eq("provincia", provincia)
    if municipio_cabecera:
        query = query.eq("municipio_cabecera", municipio_cabecera)

    try:
        res = query.limit(limit).execute()
        registros = res.data or []
        
        return {
            "status": "success",
            "total_encontrados": len(registros),
            "filtros_aplicados": {
                "especialidad_buscada": especialidad,
                "raiz_patron": pattern,
                "provincia": provincia,
                "municipio_cabecera": municipio_cabecera
            },
            "data": registros
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "data": []
        }

if __name__ == "__main__":
    # Prueba del motor con San Cristóbal
    print("🧪 PRUEBA DE BÚSQUEDA DE GEMA EN VITALMI_DIRECTORIO_MASTER:\n")
    
    resultado = consultar_directorio_master(
        especialidad="ginecologo",
        provincia="San Cristóbal"
    )
    
    print(f"Status: {resultado['status']}")
    print(f"Total encontrados: {resultado['total_encontrados']}")
    print(f"Filtros: {resultado['filtros_aplicados']}\n")
    
    if resultado["data"]:
        print("📋 Muestra del primer registro devuelto:")
        primer_reg = resultado["data"][0]
        for k, v in primer_reg.items():
            print(f"  • {k}: {v}")