import json
import logging
from typing import Optional
from app.core.supabase import obtener_cliente_supabase

logger = logging.getLogger("DirectoryTools")

def _minificar_resultados(data: list) -> str:
    """Limpia los datos de la base de datos para no saturar a OpenAI con basura técnica."""
    procesados = []
    for item in data:
        esp_oficial = item.get('especialidad_medico') or item.get('especialidad')
        esp_cons = item.get('especialidades_consolidadas')
        
        if esp_oficial:
            especialidad_final = esp_oficial
        elif isinstance(esp_cons, list) and esp_cons:
            especialidad_final = ", ".join(esp_cons)
        else:
            especialidad_final = 'General / Sin especificar'
            
        procesados.append({
            "nombre": item.get('nombre', 'Desconocido'),
            "tipo": item.get('tipo_prestador', 'Centro/Médico'),
            "especialidad": especialidad_final,
            "centro_medico": item.get('centro_medico', 'No especificado'),
            "direccion": f"{item.get('direccion', '')}, {item.get('sector', '')}, {item.get('municipio_cabecera', '')}".strip(" ,"),
            "telefono": item.get('telefono_institucional') or 'No disponible',
            "whatsapp": item.get('whatsapp') or 'No disponible'
        })
    return json.dumps({"total": len(procesados), "resultados": procesados}, ensure_ascii=False)

def buscar_directorio_salud(ubicacion: str, tipo_busqueda: str, termino: str = "", limite: int = 15) -> str:
    """
    Herramienta unificada de descubrimiento.
    tipo_busqueda puede ser: 'medico', 'centro', 'farmacia', 'nombre_especifico'
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Error de conexión a la base de datos."})

    try:
        logger.info(f"🔎 BUSCANDO: Tipo='{tipo_busqueda}', Término='{termino}', Ubicación='{ubicacion}'")
        
        # Iniciar la consulta base (Cerco Geográfico)
        query = supabase.table("vitalmi_directorio_master").select("*")
        
        if ubicacion and ubicacion.lower() not in ["republica dominicana", "país", "nacional"]:
            # Filtro flexible para la ubicación (provincia, municipio o sector)
            query = query.or_(f"provincia.ilike.%{ubicacion}%,municipio_cabecera.ilike.%{ubicacion}%,sector.ilike.%{ubicacion}%")

        # Aplicar filtros según la lógica de la intención
        termino_limpio = termino.strip()

        if tipo_busqueda == 'medico' and termino_limpio:
            query = query.or_(f"especialidad_medico.ilike.%{termino_limpio}%,especialidades_consolidadas.ilike.%{termino_limpio}%")
            
        elif tipo_busqueda == 'centro':
            termino_centro = termino_limpio if termino_limpio else "hospital"
            query = query.or_(f"tipo_prestador.ilike.%{termino_centro}%,centro_medico.ilike.%{termino_centro}%")
            
        elif tipo_busqueda == 'farmacia':
            query = query.or_("tipo_prestador.ilike.%farmacia%,centro_medico.ilike.%farmacia%")
            if termino_limpio:
                query = query.ilike("nombre", f"%{termino_limpio}%")
                
        elif tipo_busqueda == 'nombre_especifico' and termino_limpio:
            query = query.ilike("nombre", f"%{termino_limpio}%")

        # Ejecutar y retornar
        res = query.limit(limite).execute()
        
        if not res.data:
            return json.dumps({"mensaje": f"No se encontraron resultados para {termino} en {ubicacion}."})
            
        return _minificar_resultados(res.data)

    except Exception as e:
        logger.error(f"❌ Error en buscar_directorio_salud: {e}")
        return json.dumps({"error": "Fallo interno al consultar el directorio."})

def buscar_hospitales_emergencia(ubicacion: str) -> str:
    """
    Herramienta de Crisis: Busca exclusivamente centros médicos y hospitales para emergencias.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Base de datos desconectada."})

    try:
        logger.info(f"🚨 PROTOCOLO DE EMERGENCIA ACTIVADO PARA: {ubicacion}")
        query = supabase.table("vitalmi_directorio_master").select("*")
        query = query.or_(f"tipo_prestador.ilike.%hospital%,tipo_prestador.ilike.%clinica%,centro_medico.ilike.%hospital%")
        
        if ubicacion:
            query = query.or_(f"provincia.ilike.%{ubicacion}%,municipio_cabecera.ilike.%{ubicacion}%,sector.ilike.%{ubicacion}%")
            
        res = query.limit(5).execute()
        
        if not res.data:
             return json.dumps({"mensaje": "ATENCIÓN: No se detectaron hospitales en la base de datos para esta área exacta. Sugiera contactar al 911 de inmediato."})
             
        return _minificar_resultados(res.data)
        
    except Exception as e:
        logger.error(f"❌ Error en emergencias: {e}")
        return json.dumps({"error": "Sugiera llamar al Sistema Nacional de Emergencias 911."})