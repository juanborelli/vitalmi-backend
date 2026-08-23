import asyncio
import aiohttp
import re
from app.core.supabase_client import supabase

URL_MAPFRE_API = "https://servicios.mapfresaludars.com.do/providerInfo"

# Encabezados extraídos directamente del curl oficial de Mapfre
HEADERS = {
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'es,es-419;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest'
}

# Cookies de sesión vigentes extraídas del portal
COOKIES = {
    '_ga': 'GA1.1.823579554.1786851165',
    '_fbp': 'fb.2.1787148268882.394044140310773563',
    'XSRF-TOKEN': 'eyJpdiI6InVLYWJSb3h1WGMvY0NhY2Q5OUdLMVE9PSIsInZhbHVlIjoiM0I0cE5KWHhrdnBGcjFNNy9leEJERlNsbHQ3RGJMdXlkTWxvbjVEbE0ydjVIR3JjcGx3TkVDaFBkTXVaOWNUZkFaTVdMRXk2S0xxb0dhaEFZV0ZWVnNFQmJCMllYUGhLU3lRNkpRRDVXd24rU0RObzlyN2FzWmVlZWhQVGpIVTQiLCJtYWMiOiIzNjY4MDhiMjNmODNlMmIzMjM4NTM4YmZmYmExOWVjZDc5OGVjM2Vh3Y202YzFkYzEyNmFmY2QwYmIwMTZkIiwidGFnIjoiIn0=',
    'mapfre_salud_ars_session': 'eyJpdiI6InBUc3lNK3EwTFJLcjdMNGFuc2h1U1E9PSIsInZhbHVlIjoiakpLM093WENFTlpLcTFFbkJiUU9YTFFLQTJVMXRKY0NxWEFUZXJ2WXhGMlQ2cHN3RCtNN09XY2ZZemFvYWF6cnVaRS9QeUU2RW04dGpjSEYzY05WRyt5eDhlNHNkaXdYYnl2QmY1SVc4TytVdzJaTlNRd3NYOU9DdHhZeUdOK2UiLCJtYWMiOiIwN2U1ZjVkMTdmYjY0MDkxNTc0YmFjZDgxMWJmMWQ0MGQ0YmU3OWViZGIyNmM2YzFkYzEyNmFmY2QwYmIwMTZkIiwidGFnIjoiIn0='
}

# Códigos de categoría de Mapfre para la ruta /providerInfo/{tipo_id}/{centro_id}
TIPOS_CENTRO = [42, 43, 44, 45, 46, 47]

def extraer_whatsapp(lista_telefonos):
    for tel in lista_telefonos:
        limpio = re.sub(r'\D', '', str(tel))
        if len(limpio) == 10 and limpio.startswith(('809', '829', '849')):
            return f"1{limpio}"
        elif len(limpio) == 11 and limpio.startswith('1') and limpio[1:].startswith(('809', '829', '849')):
            return limpio
    return None

async def consultar_centro_mapfre(session, tipo_id, centro_id, semaphore):
    async with semaphore:
        url = f"{URL_MAPFRE_API}/{tipo_id}/{centro_id}"
        try:
            async with session.get(url, headers=HEADERS, cookies=COOKIES, timeout=5) as res:
                if res.status == 200:
                    data = await res.json()
                    if isinstance(data, dict) and data.get("nombre"):
                        return data
        except Exception:
            pass
        return None

def clasificar_y_guardar_centros(datos_raw):
    c_clinicas, f_farmacias, l_laboratorios, d_dentales, cd_diagnosticos, ce_especializados = [], [], [], [], [], []

    for d in datos_raw:
        try:
            codigo = str(d.get("id") or d.get("codigo") or "").strip()
            nombre = str(d.get("nombre") or "").strip()
            if not nombre or not codigo:
                continue

            tipo_orig = str(d.get("tipo") or d.get("categoria") or "").upper().strip()
            direccion = str(d.get("direccion") or "No especificada").strip()
            ciudad = str(d.get("ciudad") or d.get("provincia") or "No especificada").strip()
            sector = str(d.get("sector") or "No especificado").strip()

            tels_raw = d.get("telefonos") or d.get("telefono") or []
            tels = [str(t.get("numero") if isinstance(t, dict) else t).strip() for t in tels_raw if str(t).strip()] if isinstance(tels_raw, list) else [str(tels_raw).strip()]
            tel_str = " / ".join(list(dict.fromkeys(tels))) if tels else "No disponible"
            whatsapp_num = extraer_whatsapp(tels)

            registro = {
                "id": f"MAP-NOMED-{codigo}",
                "nombre": nombre,
                "direccion": direccion,
                "ciudad_provincia": ciudad,
                "sector": sector,
                "telefonos": tel_str,
                "whatsapp": whatsapp_num,
                "planes_aceptados": "Todos los planes",
                "ars": "Mapfre Salud ARS"
            }

            if "FARMACIA" in tipo_orig or "FARMACIA" in nombre.upper():
                registro["tipo_prestador"] = "FARMACIA"
                f_farmacias.append(registro)
            elif "LABORATORIO" in tipo_orig or "LABORATORIO" in nombre.upper():
                registro["tipo_prestador"] = "LABORATORIO"
                l_laboratorios.append(registro)
            elif "DENTAL" in tipo_orig or "ODONTOL" in tipo_orig or "DENTAL" in nombre.upper():
                registro["tipo_prestador"] = "DENTALES"
                d_dentales.append(registro)
            elif "DIAGNOSTICO" in tipo_orig:
                registro["tipo_prestador"] = "CENTRO DIAGNOSTICOS"
                cd_diagnosticos.append(registro)
            elif "ESPECIALIZADO" in tipo_orig:
                registro["tipo_prestador"] = "CENTRO ESPECIALIZADO"
                ce_especializados.append(registro)
            else:
                registro["tipo_prestador"] = "CLINICA"
                c_clinicas.append(registro)

        except Exception:
            continue

    tablas_mapa = [
        ("clinica_mapfre", c_clinicas),
        ("farmacia_mapfre", f_farmacias),
        ("laboratorio_mapfre", l_laboratorios),
        ("dentales_mapfre", d_dentales),
        ("centro_diagnosticos_mapfre", cd_diagnosticos),
        ("centro_especializado_mapfre", ce_especializados)
    ]

    for tabla, datos in tablas_mapa:
        if datos:
            supabase.table(tabla).upsert(datos, on_conflict="id").execute()
            print(f"   ✅ [{tabla.upper()}] Guardados {len(datos)} registros de la API.")

async def ejecutar_extraccion_no_medicos_mapfre():
    print("=== 🚀 EXTRACCIÓN DIRECTA DE NO MÉDICOS DE MAPFRE (API REST) ===")
    semaphore = asyncio.Semaphore(50)
    
    # Rango denso basado en el ID del curl (8262515)
    rango_ids = range(8262000, 8263500)

    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        for tipo_id in TIPOS_CENTRO:
            print(f"\n📡 Consultando Categoría Tipo ID: {tipo_id}...")
            tasks = [consultar_centro_mapfre(session, tipo_id, c_id, semaphore) for c_id in rango_ids]
            resultados = await asyncio.gather(*tasks)
            validos = [r for r in resultados if r is not None]
            if validos:
                clasificar_y_guardar_centros(validos)

if __name__ == "__main__":
    asyncio.run(ejecutar_extraccion_no_medicos_mapfre())