import os
import json
import logging
import meilisearch
from typing import Optional

logger = logging.getLogger("DirectoryTools")

# 1. Leer las variables del servidor (Railway)
MEILI_URL = os.getenv("MEILISEARCH_URL", "http://127.0.0.1:7700")
MEILI_KEY = os.getenv("MEILISEARCH_MASTER_KEY", "clave_maestra_local_vitalmi_123")

# 2. Imprimir en los logs para confirmar qué URL está usando realmente
logger.info(f"🔧 Conectando Meilisearch a: {MEILI_URL}")

try:
    meili = meilisearch.Client(MEILI_URL, MEILI_KEY)
    index = meili.index('prestadores')
except Exception as e:
    logger.error(f"❌ Error al inicializar Meilisearch: {e}")