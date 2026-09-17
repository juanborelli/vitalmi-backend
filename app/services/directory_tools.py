import os
import json
import logging
import meilisearch
from typing import Optional

logger = logging.getLogger("DirectoryTools")

# Configurar cliente Meilisearch con variables de entorno
MEILI_URL = os.getenv("MEILISEARCH_URL", "http://127.0.0.1:7700")
MEILI_KEY = os.getenv("MEILISEARCH_MASTER_KEY", "clave_maestra_local_vitalmi_123")

logger.info(f"🔧 Conectando Meilisearch a: {MEILI_URL}")

try:
    meili = meilisearch.Client(MEILI_URL, MEILI_KEY)
    index = meili.index('prestadores')
except Exception as e:
    logger.error(f"❌ Error al inicializar Meilisearch: {e}")

def _minificar_resultados(data: list) -> str:
    """Limpia y estructura los datos exponiendo explícitamente Telefonos Institucionales y WhatsApp."""
    procesados = []
    for item in data:
        esp_oficial = item.get('especialidad_medico') or item.get('especialidad')
        esp_cons = item.get('especialidades_consolidadas')
        
        if esp_oficial:
            especialidad_final = esp_oficial
        elif isinstance(esp_cons, list) and esp_cons:
            especialidad_final = ", ".join(esp_cons)
        else:
            especialidad_final = 'Medicina General / Especialidad no especificada'
            
        telefono_inst = item.get('telefono_institucional') or item.get('telefono') or 'No disponible'
        whatsapp_val = item.get('whatsapp') or 'No disponible'
            
        procesados.append({
            "nombre": item.get('nombre', 'Desconocido'),
            "tipo": item.get('tipo_prestador', 'Centro/Médico'),
            "especialidad": especialidad_final,
            "centro_medico": item.get('centro_medico', 'No especificado'),
            "direccion": f"{item.get('direccion', '')}, {item.get('sector', '')}, {item.get('municipio_cabecera', '')}, {item.get('provincia', '')}".strip(" ,"),
            "telefono_institucional": telefono_inst,
            "whatsapp": whatsapp_val
        })
    return json.dumps({"total": len(procesados), "resultados": procesados}, ensure_ascii=False)

def buscar_directorio_salud(ubicacion: str, tipo_busqueda: str, termino: str = "", limite: int = 15) -> str:
    """Búsqueda avanzada con soporte nacional y filtros geográficos estrictos."""
    try:
        termino_limpio = termino.strip() if termino else tipo_busqueda
        ubicacion_limpia = ubicacion.strip() if ubicacion else ""
        
        logger.info(f"🔎 MEILISEARCH BÚSQUEDA: Término='{termino_limpio}', Ubicación='{ubicacion_limpia}'")
        
        es_busqueda_abierta = not ubicacion_limpia or ubicacion_limpia.lower() in ["republica dominicana", "rd", "pais", "todo el pais", "sin importar la ciudad"]
        
        search_params = {
            'limit': limite,
            'matchingStrategy': 'all'
        }
        
        query_final = termino_limpio

        if not es_busqueda_abierta:
            loc_title = ubicacion_limpia.title()
            search_params['filter'] = f"provincia = '{loc_title}' OR municipio_cabecera = '{loc_title}' OR sector = '{loc_title}'"
            query_final = f"{termino_limpio} {ubicacion_limpia}".strip()
            search_params['matchingStrategy'] = 'last'

        res = index.search(query_final, search_params)
        hits = res.get('hits', [])
        
        if not hits and not es_busqueda_abierta:
            logger.warning(f"⚠️ Sin resultados estrictos para '{ubicacion_limpia}'. Intentando búsqueda flexible con texto...")
            search_params.pop('filter', None)
            res_alt = index.search(f"{termino_limpio} {ubicacion_limpia}", {'limit': limite, 'matchingStrategy': 'last'})
            hits = res_alt.get('hits', [])

        if not hits:
            return json.dumps({"mensaje": f"No se encontraron registros para '{termino_limpio}' en la ubicación especificada."})
            
        return _minificar_resultados(hits)

    except Exception as e:
        logger.error(f"❌ Error crítico en buscar_directorio_salud: {e}")
        return json.dumps({"error": "Fallo interno al consultar el directorio de salud."})

def buscar_hospitales_emergencia(ubicacion: str) -> str:
    """Protocolo de emergencia geolocalizado estrictamente a la zona solicitada"""
    try:
        ubicacion_limpia = ubicacion.strip() if ubicacion else "San Cristóbal"
        logger.info(f"🚨 EMERGENCIA MEILISEARCH PARA: {ubicacion_limpia}")
        
        query = f"hospital clinica emergencia {ubicacion_limpia}".strip()
        loc_title = ubicacion_limpia.title()
        
        search_params = {
            'limit': 5,
            'matchingStrategy': 'last',
            'filter': f"provincia = '{loc_title}' OR municipio_cabecera = '{loc_title}' OR sector = '{loc_title}'"
        }
        
        res = index.search(query, search_params)
        hits = res.get('hits', [])
        
        if not hits:
            logger.warning(f"⚠️ Sin hospitales estrictos para '{ubicacion_limpia}'. Relajando filtro geográfico local...")
            search_params.pop('filter', None)
            res_alt = index.search(query, search_params)
            hits = res_alt.get('hits', [])
        
        if not hits:
             return json.dumps({"mensaje": f"ATENCIÓN: No se detectaron hospitales locales en {ubicacion_limpia}. Por favor, contacte al Sistema Nacional de Emergencias 911 de inmediato."})
             
        return _minificar_resultados(hits)
        
    except Exception as e:
        logger.error(f"❌ Error en emergencias: {e}")
        return json.dumps({"error": "Sugiera llamar al Sistema Nacional de Emergencias 911."})