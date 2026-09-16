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
    
    # Configurar atributos filtrables en Meilisearch para garantizar precisión geográfica
    index.update_filterable_attributes([
        "provincia",
        "municipio_cabecera",
        "sector",
        "tipo_prestador",
        "centro_medico"
    ])
except Exception as e:
    logger.error(f"❌ Error al inicializar o configurar Meilisearch: {e}")

def _minificar_resultados(data: list) -> str:
    """Limpia y estructura los datos asegurando que la especialidad y los datos clave nunca falten."""
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
            
        procesados.append({
            "nombre": item.get('nombre', 'Desconocido'),
            "tipo": item.get('tipo_prestador', 'Centro/Médico'),
            "especialidad": especialidad_final,
            "centro_medico": item.get('centro_medico', 'No especificado'),
            "direccion": f"{item.get('direccion', '')}, {item.get('sector', '')}, {item.get('municipio_cabecera', '')}".strip(" ,"),
            "telefono": item.get('telefono_institucional') or item.get('telefono') or 'No disponible',
            "whatsapp": item.get('whatsapp') or 'No disponible'
        })
    return json.dumps({"total": len(procesados), "resultados": procesados}, ensure_ascii=False)

def buscar_directorio_salud(ubicacion: str, tipo_busqueda: str, termino: str = "", limite: int = 15) -> str:
    """Búsqueda avanzada con filtros geográficos estrictos en Meilisearch"""
    try:
        termino_limpio = termino.strip() if termino else tipo_busqueda
        logger.info(f"🔎 MEILISEARCH BÚSQUEDA ESTRICTA: Término='{termino_limpio}', Ubicación='{ubicacion}'")
        
        # Construir filtro estricto por ubicación para evitar alucinaciones geográficas
        filtros = []
        if ubicacion and ubicacion.lower() not in ["republica dominicana", "rd", "pais"]:
            loc_limpia = ubicacion.strip().title()
            # Filtramos si coincide con provincia o municipio cabecera
            filtros.append(f"provincia = '{loc_limpia}' OR municipio_cabecera = '{loc_limpia}' OR sector = '{loc_limpia}'")

        search_params = {
            'limit': limite
        }
        
        if filtros:
            search_params['filter'] = " OR ".join(filtros)

        # Ejecutar búsqueda en Meilisearch
        res = index.search(termino_limpio, search_params)
        hits = res.get('hits', [])
        
        # Fallback de seguridad: si el filtro estricto no arroja nada por variaciones de texto en la BD,
        # intentamos una búsqueda abierta pero priorizando la honestidad en el resultado.
        if not hits and filtros:
            logger.warning(f"⚠️ Sin resultados estrictos para '{loc_limpia}'. Intentando búsqueda abierta de respaldo...")
            query_alternativa = f"{termino_limpio} {ubicacion}".strip()
            res_alt = index.search(query_alternativa, {'limit': limite})
            hits = res_alt.get('hits', [])

        if not hits:
            return json.dumps({"mensaje": f"No se encontraron registros exactos para '{termino_limpio}' en '{ubicacion}'."})
            
        return _minificar_resultados(hits)

    except Exception as e:
        logger.error(f"❌ Error crítico en buscar_directorio_salud: {e}")
        return json.dumps({"error": "Fallo interno al consultar el directorio de salud."})

def buscar_hospitales_emergencia(ubicacion: str) -> str:
    """Protocolo de emergencia geolocalizado"""
    try:
        logger.info(f"🚨 EMERGENCIA MEILISEARCH PARA: {ubicacion}")
        query = f"hospital clinica emergencia {ubicacion}".strip()
        res = index.search(query, {'limit': 5})
        hits = res.get('hits', [])
        
        if not hits:
             return json.dumps({"mensaje": "ATENCIÓN: No se detectaron hospitales locales. Sugiera contactar al Sistema Nacional de Emergencias 911 de inmediato."})
             
        return _minificar_resultados(hits)
        
    except Exception as e:
        logger.error(f"❌ Error en emergencias: {e}")
        return json.dumps({"error": "Sugiera llamar al Sistema Nacional de Emergencias 911."})