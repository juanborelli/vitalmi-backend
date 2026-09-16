import json
import logging
import meilisearch
from typing import Optional
from app.core.supabase import obtener_cliente_supabase

logger = logging.getLogger("DirectoryTools")

# Inicializar cliente Meilisearch (Apunta a tu motor local temporalmente)
try:
    meili = meilisearch.Client('http://127.0.0.1:7700', 'clave_maestra_local_vitalmi_123')
    index = meili.index('prestadores')
except Exception as e:
    logger.error(f"❌ Error conectando a Meilisearch: {e}")

def _minificar_resultados(data: list) -> str:
    """Limpia los datos para no saturar a OpenAI con basura técnica."""
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
    """Herramienta unificada usando el motor ultrarrápido de Meilisearch"""
    try:
        logger.info(f"🔎 MEILISEARCH BUSCANDO: Tipo='{tipo_busqueda}', Término='{termino}', Ubicación='{ubicacion}'")
        
        # Unimos los términos naturales. Si alguien escribe mal "cardioloho en bani", Meilisearch lo entenderá.
        termino_limpio = termino.strip() if termino else tipo_busqueda
        query = f"{termino_limpio} {ubicacion}".strip()
        
        # Búsqueda instantánea
        res = index.search(query, {
            'limit': limite
        })
        
        hits = res.get('hits', [])
        if not hits:
            return json.dumps({"mensaje": f"No se encontraron resultados para {termino} en {ubicacion}."})
            
        return _minificar_resultados(hits)

    except Exception as e:
        logger.error(f"❌ Error en buscar_directorio_salud (Meilisearch): {e}")
        return json.dumps({"error": "Fallo interno al consultar el directorio."})

def buscar_hospitales_emergencia(ubicacion: str) -> str:
    """Herramienta de Crisis impulsada por Meilisearch"""
    try:
        logger.info(f"🚨 PROTOCOLO DE EMERGENCIA MEILISEARCH PARA: {ubicacion}")
        
        # Forzamos términos clave de emergencia
        query = f"hospital clinica emergencia {ubicacion}".strip()
        
        res = index.search(query, {
            'limit': 5
        })
        
        hits = res.get('hits', [])
        if not hits:
             return json.dumps({"mensaje": "ATENCIÓN: No se detectaron hospitales. Sugiera contactar al 911 de inmediato."})
             
        return _minificar_resultados(hits)
        
    except Exception as e:
        logger.error(f"❌ Error en emergencias: {e}")
        return json.dumps({"error": "Sugiera llamar al Sistema Nacional de Emergencias 911."})