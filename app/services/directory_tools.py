import os
import json
import logging
import meilisearch
from typing import Optional

logger = logging.getLogger("DirectoryTools")

# Leer configuraciones de Railway con respaldo local
MEILI_URL = os.getenv("MEILISEARCH_URL", "http://127.0.0.1:7700")
MEILI_KEY = os.getenv("MEILISEARCH_MASTER_KEY", "clave_maestra_local_vitalmi_123")

logger.info(f"🔧 Conectando Meilisearch a: {MEILI_URL}")

try:
    meili = meilisearch.Client(MEILI_URL, MEILI_KEY)
    index = meili.index('prestadores')
except Exception as e:
    logger.error(f"❌ Error al inicializar Meilisearch: {e}")

def _minificar_resultados(data: list) -> str:
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
    """Función requerida por gema_brain.py para consultar Meilisearch"""
    try:
        logger.info(f"🔎 MEILISEARCH BUSCANDO: Tipo='{tipo_busqueda}', Término='{termino}', Ubicación='{ubicacion}'")
        
        termino_limpio = termino.strip() if termino else tipo_busqueda
        query = f"{termino_limpio} {ubicacion}".strip()
        
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
    """Protocolo de emergencia"""
    try:
        logger.info(f"🚨 PROTOCOLO DE EMERGENCIA MEILISEARCH PARA: {ubicacion}")
        query = f"hospital clinica emergencia {ubicacion}".strip()
        res = index.search(query, {'limit': 5})
        hits = res.get('hits', [])
        if not hits:
             return json.dumps({"mensaje": "ATENCIÓN: No se detectaron hospitales. Sugiera contactar al 911 de inmediato."})
        return _minificar_resultados(hits)
    except Exception as e:
        logger.error(f"❌ Error en emergencias: {e}")
        return json.dumps({"error": "Sugiera llamar al Sistema Nacional de Emergencias 911."})