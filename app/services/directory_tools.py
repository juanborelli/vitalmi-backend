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
            "direccion": f"{item.get('direccion', '')}, {item.get('sector', '')}, {item.get('municipio_cabecera', '')}, {item.get('provincia', '')}".strip(" ,"),
            "telefono": item.get('telefono_institucional') or item.get('telefono') or 'No disponible',
            "whatsapp": item.get('whatsapp') or 'No disponible'
        })
    return json.dumps({"total": len(procesados), "resultados": procesados}, ensure_ascii=False)

def buscar_directorio_salud(ubicacion: str, tipo_busqueda: str, termino: str = "", limite: int = 15) -> str:
    """Búsqueda avanzada universal con soporte nacional y filtrado flexible."""
    try:
        termino_limpio = termino.strip() if termino else tipo_busqueda
        ubicacion_limpia = ubicacion.strip() if ubicacion else ""
        
        logger.info(f"🔎 MEILISEARCH BÚSQUEDA UNIVERSAL: Término='{termino_limpio}', Ubicación='{ubicacion_limpia}'")
        
        # Consideramos abierta o nacional si no hay ubicación o si es la referencia genérica por defecto
        es_busqueda_abierta = not ubicacion_limpia or ubicacion_limpia.lower() in ["republica dominicana", "rd", "pais", "todo el pais", "sin importar la ciudad", "san cristóbal", "san cristobal"]
        
        if es_busqueda_abierta:
            query_final = termino_limpio
            search_params = {
                'limit': limite,
                'matchingStrategy': 'all'
            }
        else:
            # Si es un sector o provincia muy específica (ej: Naco, Piantini, Barahona)
            query_final = f"{termino_limpio} {ubicacion_limpia}".strip()
            search_params = {
                'limit': limite,
                'matchingStrategy': 'last'  # Corregido: 'last' es el valor válido en Meilisearch
            }

        # Ejecutar búsqueda en Meilisearch
        res = index.search(query_final, search_params)
        hits = res.get('hits', [])
        
        # Fallback de seguridad: si no encuentra con la combinación, busca solo por el término principal
        if not hits:
            logger.warning(f"⚠️ Sin resultados para '{query_final}'. Intentando búsqueda libre por término...")
            res_alt = index.search(termino_limpio, {'limit': limite, 'matchingStrategy': 'all'})
            hits = res_alt.get('hits', [])

        if not hits:
            return json.dumps({"mensaje": f"No se encontraron registros para '{termino_limpio}' en la ubicación especificada."})
            
        return _minificar_resultados(hits)

    except Exception as e:
        logger.error(f"❌ Error crítico en buscar_directorio_salud: {e}")
        return json.dumps({"error": "Fallo interno al consultar el directorio de salud."})

def buscar_hospitales_emergencia(ubicacion: str) -> str:
    """Protocolo de emergencia geolocalizado"""
    try:
        logger.info(f"🚨 EMERGENCIA MEILISEARCH PARA: {ubicacion}")
        query = f"hospital clinica emergencia {ubicacion}".strip()
        
        res = index.search(query, {
            'limit': 5,
            'matchingStrategy': 'last' # Corregido aquí también por seguridad
        })
        hits = res.get('hits', [])
        
        if not hits:
             return json.dumps({"mensaje": "ATENCIÓN: No se detectaron hospitales locales. Sugiera contactar al Sistema Nacional de Emergencias 911 de inmediato."})
             
        return _minificar_resultados(hits)
        
    except Exception as e:
        logger.error(f"❌ Error en emergencias: {e}")
        return json.dumps({"error": "Sugiera llamar al Sistema Nacional de Emergencias 911."})