import asyncio
import aiohttp
import json
import os
import re
import pandas as pd
from bs4 import BeautifulSoup

# Configuración
URL_BASE = "https://servicios.mapfresaludars.com.do/providerInfo/99/"
CARPETA_SALIDA = "json_medicos_nacional"
os.makedirs(CARPETA_SALIDA, exist_ok=True)

HEADERS = {
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest'
}

COOKIES = {
    '_ga': 'GA1.1.823579554.1786851165',
    'XSRF-TOKEN': 'eyJpdiI6IlVWN2dPTStZNDM0YzZPdW9Db3UzU0E9PSIsInZhbHVlIjoiQ2RUZi9lRU1MVGxvUXNsV3lOS2crT0RMTFdJaHhWL01aTzFQQXdFWnRSWSsxUHVTRnFQQ2d2K3QwRkozYWVjcGQ4MlRUMERIYnRqbFFBeEZJZXVNNnpVQi9wZUhCREc1Q3lya1VyUXl2R1Y2UVBRKzFVdnArWjdYR2RQc0JvSlkiLCJtYWMiOiIyZjJhOTMwODA4ZDU3NjQxODFjMDJmOThhNjU2OGM3ZDVmYjVjYTNiMjU1MDU4NmU1ZmEwZmZjMGM0ODBlNjEyIiwidGFnIjoiIn0=',
    'mapfre_salud_ars_session': 'eyJpdiI6IjMxVXB4cXdsZEpYcVZicTN6Vk9kWHc9PSIsInZhbHVlIjoiM01FWW0vekpPYTU4TWZ3K1VJYXhadnhVN3RHOEN0RS94WnlhVi83QTJHRW55WC9Oem9jMlFhbXJZaVhTRW9jTi9qSjV1T2JucysvS0xvdmNnREI2UkNja0hQTjU0Y3dSQnFsa0lmNXptSTVXeFV6N2RWdlExQXlrMHdtaG1Ib28iLCJtYWMiOiJlYjdmYTM2ZjEzOWU4N2Y4OTI2NDFiZjk2NGM5YWNhMWU5MDNjZjA4NTRiNzNkMTcxOTYxNTE3M2Y5YjUyOTgxIiwidGFnIjoiIn0='
}

def extraer_todos_los_ids():
    """Busca patrones de IDs numéricos en todos los archivos .html del proyecto."""
    archivos_html = []
    for root, _, files in os.walk("."):
        if any(ignore in root for ignore in ["venv", "node_modules", ".git"]):
            continue
        for f in files:
            if f.endswith(".html"):
                archivos_html.append(os.path.join(root, f))

    print(f"📂 Archivos HTML localizados: {len(archivos_html)}")
    ids_encontrados = []

    for ruta in archivos_html:
        try:
            with open(ruta, "r", encoding="utf-8", errors="ignore") as f:
                contenido = f.read()
                
            # Patrones flexibles para capturar los IDs de los médicos
            patrones = [
                r'providerInfo/\d+/(\d+)',
                r'providerInfo/(\d+)',
                r'data-id=["\'](\d+)["\']',
                r'data-provider=["\'](\d+)["\']',
                r'id_proveedor=["\'](\d+)["\']',
                r'verMedico\(["\']?(\d+)["\']?\)',
                r'detail/(\d+)',
                r'href=["\'].*?(\d{6,8})["\']'
            ]

            for pat in patrones:
                coincidencias = re.findall(pat, contenido)
                ids_encontrados.extend(coincidencias)

        except Exception as e:
            print(f"⚠️ Error al leer {ruta}: {e}")

    # Filtrar IDs válidos de entre 6 y 8 dígitos
    ids_validos = [i for i in ids_encontrados if 100000 <= int(i) <= 99999999]
    ids_unicos = list(dict.fromkeys(ids_validos))
    
    print(f"🎯 IDs de médicos válidos detectados: {len(ids_unicos)}")
    return ids_unicos

async def descargar_ficha(session, id_medico, semaphore, total, contador):
    async with semaphore:
        url = f"{URL_BASE}{id_medico}"
        archivo = os.path.join(CARPETA_SALIDA, f"medico_{id_medico}.json")
        
        if os.path.exists(archivo):
            contador[0] += 1
            return True

        try:
            async with session.get(url, headers=HEADERS, cookies=COOKIES, timeout=6) as res:
                if res.status == 200:
                    data = await res.json()
                    if data and isinstance(data, dict) and data.get("name"):
                        with open(archivo, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        contador[0] += 1
                        if contador[0] % 10 == 0 or contador[0] == total:
                            print(f"   ⚡ [{contador[0]}/{total}] Guardado: {data.get('name')} ({data.get('city', '')})")
                        return True
        except Exception:
            pass
        
        return False

async def ejecutar_descarga_masiva():
    print("=== 🚀 INICIANDO EXTRACTOR DE DIRECTORIO COMPLETO ===")
    ids = extraer_todos_los_ids()
    
    if not ids:
        print("❌ No se encontraron patrones de IDs en los archivos HTML locales.")
        return

    print(f"\n⚡ Descargando {len(ids)} fichas en paralelo (25 conexiones simultáneas)...")
    semaphore = asyncio.Semaphore(25)
    contador = [0]
    total = len(ids)

    async with aiohttp.ClientSession() as session:
        tasks = [descargar_ficha(session, med_id, semaphore, total, contador) for med_id in ids]
        resultados = await asyncio.gather(*tasks)

    exitos = sum(1 for r in resultados if r)
    print(f"\n🎉 PROCESO COMPLETADO: {exitos} de {len(ids)} fichas de médicos guardadas en '{CARPETA_SALIDA}/'.")

if __name__ == "__main__":
    asyncio.run(ejecutar_descarga_masiva())