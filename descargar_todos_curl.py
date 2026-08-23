import os
import json
import time
import requests
import pandas as pd

def descargar_y_procesar_medicos():
    print("=== 🚀 INICIANDO DESCARGA DIRECTA DESDE API MAPFRE ===")
    
    carpeta_json = "json_medicos"
    os.makedirs(carpeta_json, exist_ok=True)

    url_base = "https://servicios.mapfresaludars.com.do/providerInfo/99/"

    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'es,es-419;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'sec-ch-ua': '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"'
    }

    cookies = {
        '_ga': 'GA1.1.823579554.1786851165',
        'XSRF-TOKEN': 'eyJpdiI6IlVWN2dPTStZNDM0YzZPdW9Db3UzU0E9PSIsInZhbHVlIjoiQ2RUZi9lRU1MVGxvUXNsV3lOS2crT0RMTFdJaHhWL01aTzFQQXdFWnRSWSsxUHVTRnFQQ2d2K3QwRkozYWVjcGQ4MlRUMERIYnRqbFFBeEZJZXVNNnpVQi9wZUhCREc1Q3lya1VyUXl2R1Y2UVBRKzFVdnArWjdYR2RQc0JvSlkiLCJtYWMiOiIyZjJhOTMwODA4ZDU3NjQxODFjMDJmOThhNjU2OGM3ZDVmYjVjYTNiMjU1MDU4NmU1ZmEwZmZjMGM0ODBlNjEyIiwidGFnIjoiIn0=',
        'mapfre_salud_ars_session': 'eyJpdiI6IjMxVXB4cXdsZEpYcVZicTN6Vk9kWHc9PSIsInZhbHVlIjoiM01FWW0vekpPYTU4TWZ3K1VJYXhadnhVN3RHOEN0RS94WnlhVi83QTJHRW55WC9Oem9jMlFhbXJZaVhTRW9jTi9qSjV1T2JucysvS0xvdmNnREI2UkNja0hQTjU0Y3dSQnFsa0lmNXptSTVXeFV6N2RWdlExQXlrMHdtaG1Ib28iLCJtYWMiOiJlYjdmYTM2ZjEzOWU4N2Y4OTI2NDFiZjk2NGM5YWNhMWU5MDNjZjA4NTRiNzNkMTcxOTYxNTE3M2Y5YjUyOTgxIiwidGFnIjoiIn0='
    }

    # Probar con un rango de IDs alrededor de 8272896
    # Si tienes la lista de IDs de la tabla, los podemos pasar directo
    id_inicio = 8272800
    id_fin = 8273000

    descargados = 0

    for id_medico in range(id_inicio, id_fin):
        url = f"{url_base}{id_medico}"
        
        try:
            res = requests.get(url, headers=headers, cookies=cookies, timeout=5)
            if res.status_code == 200:
                try:
                    data = res.json()
                    if data and isinstance(data, dict) and data.get("name"):
                        archivo = os.path.join(carpeta_json, f"medico_{id_medico}.json")
                        with open(archivo, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
                        
                        descargados += 1
                        print(f"   ✅ [{descargados}] ID {id_medico}: {data.get('name')} | Tel: {data.get('phoneNumbers', [{}])[0].get('value', 'N/A')}")
                except json.JSONDecodeError:
                    pass
            time.sleep(0.05)
        except Exception as e:
            continue

    print(f"\n🎉 Descarga completada: {descargados} fichas en '{carpeta_json}'.")

if __name__ == "__main__":
    descargar_y_procesar_medicos()