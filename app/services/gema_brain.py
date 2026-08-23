import os
import json
from typing import Dict, Any, List
from dotenv import load_dotenv
from app.core.supabase import obtener_cliente_supabase

load_dotenv(override=True)
supabase = obtener_cliente_supabase()

# System Prompt Oficial de Gema
PROMPT_SISTEMA_GEMA = """
Eres Gema, la asistente médica virtual de VitalMi en República Dominicana.
Tu objetivo es ayudar a los usuarios a encontrar médicos, clínicas, especialistas y centros de salud en la plataforma VitalMi.

Instrucciones de comportamiento:
1. Sé empática, profesional, clara y concisa.
2. Utiliza la información oficial provista por la base de datos de VitalMi (vitalmi_directorio_master).
3. Si la búsqueda devuelve resultados, preséntalos organizados con nombre, especialidad, centro médico, provincia y teléfono de contacto.
4. Si no se especifican provincia o aseguradora, busca de manera amplia pero ofrece al usuario filtrar por su ubicación para ser más precisa.
"""

MAPEO_RAICES_ESPECIALIDAD = {
    "ginecologia": "GINEC", "ginecologo": "GINEC", "ginecologa": "GINEC", "obstetricia": "OBSTETR",
    "cardiologia": "CARDIO", "cardiologo": "CARDIO", "pediatria": "PEDIAT", "pediatra": "PEDIAT",
    "dermatologia": "DERMAT", "dermatologo": "DERMAT", "ortopedia": "ORTOP", "traumatologia": "TRAUMAT",
    "oftalmologia": "OFTALM", "neurologia": "NEUROL", "odontologia": "ODONT"
}

def obtener_raiz_especialidad(especialidad_input: str) -> str:
    clean = (especialidad_input or "").strip().lower()
    if clean in MAPEO_RAICES_ESPECIALIDAD:
        return MAPEO_RAICES_ESPECIALIDAD[clean]
    return clean[:5].upper() if len(clean) >= 5 else clean.upper()

def consultar_directorio_master(
    especialidad: str = None, 
    provincia: str = None, 
    municipio_cabecera: str = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Herramienta dinámica de consulta sobre 'vitalmi_directorio_master'
    para cualquier provincia y especialidad.
    """
    if not supabase:
        return {"status": "error", "message": "Conexión a Supabase no disponible", "data": []}

    query = supabase.table("vitalmi_directorio_master").select(
        "id, nombre, tipo_prestador, especialidad, especialidad_medico, "
        "centro_medico, direccion, provincia, municipio_cabecera, sector, "
        "telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
    )

    if especialidad:
        raiz_esp = obtener_raiz_especialidad(especialidad)
        pattern = f"%{raiz_esp}%"
        query = query.or_(
            f"especialidad.ilike.{pattern},"
            f"especialidad_medico.ilike.{pattern},"
            f"especialidad_clinica.ilike.{pattern}"
        )

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
            "data": registros
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

def obtener_respuesta_gema(mensaje_usuario: str) -> str:
    """
    Procesador principal del chat de Gema. Extrae intenciones 
    y consulta la tabla máster de manera dinámica.
    """
    # Lógica de extracción dinámica básica de entidad/ubicación
    msg_upper = (mensaje_usuario or "").upper()
    
    # Detección de provincia en la consulta
    provincia_detectada = None
    if "SAN CRISTOBAL" in msg_upper or "SAN CRISTÓBAL" in msg_upper:
        provincia_detectada = "San Cristóbal"
    elif "SANTIAGO" in msg_upper:
        provincia_detectada = "Santiago"
    elif "DISTRITO NACIONAL" in msg_upper or "SANTO DOMINGO" in msg_upper:
        provincia_detectada = "Distrito Nacional"

    # Detección de especialidad
    especialidad_detectada = None
    if "GINEC" in msg_upper:
        especialidad_detectada = "ginecologo"
    elif "CARDIO" in msg_upper:
        especialidad_detectada = "cardiologo"
    elif "PEDIAT" in msg_upper:
        especialidad_detectada = "pediatra"

    # Consulta a la base de datos máster
    res = consultar_directorio_master(
        especialidad=especialidad_detectada,
        provincia=provincia_detectada
    )
    
    total = res.get("total_encontrados", 0)
    
    if total > 0:
        loc_str = f" en {provincia_detectada}" if provincia_detectada else ""
        esp_str = f" de la especialidad solicitada" if especialidad_detectada else " médicos"
        return f"En la base de datos de VitalMi contamos con {total}{esp_str}{loc_str} registrados. ¿Deseas la información o contacto de alguno en particular?"
    
    return "Hola, soy Gema de VitalMi. No encontré registros exactos para tu búsqueda. ¿Podrías indicarme qué especialidad o provincia necesitas?"