import asyncio
import aiohttp
import re
from app.core.supabase_client import supabase

URL_MAPFRE = "https://www.mapfresaludars.com.do/wp-admin/admin-ajax.php"

HEADERS = {
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://www.mapfresaludars.com.do',
    'Referer': 'https://www.mapfresaludars.com.do/directorio-medico/',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Puntos clave con mayor probabilidad de concentración en la serie 82M
PUNTOS_CLAVE = range(82000000, 82050000, 5)

def extraer_whatsapp(lista_telefonos):
    for tel in lista_telefonos:
        limpio = re.sub(r'\D', '', str(tel))
        if len(limpio) == 10 and limpio.startswith(('809', '829', '849')):
            return f"1{limpio}"
        elif len(limpio) == 11 and limpio.startswith('1') and limpio[1:].startswith(('809', '829', '849')):
            return limpio
    return None

def obtener_ids_existentes():
    print("🔍 Consultando registros de Mapfre en Supabase...")
    ids_existentes = set()
    inicio, paso = 0, 1000
    while True:
        res = supabase.table('medico_mapfre').select('id').range(inicio, inicio + paso - 1).execute()
        if not res.data:
            break
        for r in res.data:
            clean_id = str(r['id']).replace('MAP-', '')
            if clean_id.isdigit():
                ids_existentes.add(int(clean_id))
        inicio += paso
    print(f"✅ Se omitirán {len(ids_existentes)} IDs previamente registrados.")
    return ids_existentes

async def consultar_medico(session, med_id, semaphore):
    async with semaphore:
        payload = {'action': 'get_doctor_info', 'id': str(med_id)}
        try:
            async with session.post(URL_MAPFRE, headers=HEADERS, data=payload, timeout=3) as res:
                if res.status == 200:
                    res_json = await res.json()
                    if isinstance(res_json, dict) and res_json.get("success") and res_json.get("data"):
                        return res_json["data"]
        except Exception:
            pass
        return None

def guardar_lote(datos_raw):
    medicos_batch = []
    for d in datos_raw:
        try:
            codigo = str(d.get("id") or d.get("codigo") or "").strip()
            nombre = str(d.get("nombre") or d.get("doctor_name") or "").strip()
            if not nombre or not codigo: continue

            especialidad = str(d.get("especialidad") or d.get("specialty") or "General").strip()
            centro = str(d.get("centro_medico") or d.get("hospital") or "Consulta Privada").strip()
            direccion = str(d.get("direccion") or d.get("address") or "No especificada").strip()
            ciudad = str(d.get("ciudad") or d.get("provincia") or "No especificada").strip()
            
            tels_raw = d.get("telefonos") or d.get("phone") or []
            tels = [str(t.get("numero") if isinstance(t, dict) else t).strip() for t in tels_raw if str(t).strip()] if isinstance(tels_raw, list) else [str(tels_raw).strip()]
            
            medicos_batch.append({
                "id": f"MAP-{codigo}",
                "nombre": nombre,
                "especialidad": especialidad,
                "centro_medico": centro,
                "direccion": direccion,
                "telefonos": ", ".join(list(dict.fromkeys(tels))) if tels else "No disponible",
                "whatsapp": extraer_whatsapp(tels),
                "ciudad_provincia": ciudad,
                "sector": str(d.get("sector") or "No especificado").strip(),
                "planes_aceptados": "Todos los planes",
                "tipo_prestador": "MEDICO",
                "ars": "Mapfre Salud ARS"
            })
        except Exception: continue

    if medicos_batch:
        supabase.table("medico_mapfre").upsert(medicos_batch, on_conflict="id").execute()
        print(f"   🎯 ¡CAPTURADOS! {len(medicos_batch)} nuevos médicos de Mapfre.")

async def ejecutar_ultimo_intento():
    print("=== ⚡ ÚLTIMO INTENTO ULTRA-RÁPIDO DE MÉDICOS MAPFRE ===")
    ids_existentes = obtener_ids_existentes()
    semaphore = asyncio.Semaphore(150)
    
    ids_a_consultar = [i for i in PUNTOS_CLAVE if i not in ids_existentes]
    print(f"🚀 Escaneando {len(ids_a_consultar)} puntos estratégicos en paralelo...")
    
    connector = aiohttp.TCPConnector(limit=200)
    async with aiohttp.ClientSession(connector=connector) as session:
        for i in range(0, len(ids_a_consultar), 300):
            bloque = ids_a_consultar[i:i+300]
            tasks = [consultar_medico(session, med_id, semaphore) for med_id in bloque]
            resultados = await asyncio.gather(*tasks)
            validos = [r for r in resultados if r is not None]
            if validos:
                guardar_lote(validos)
            else:
                print(f"   ℹ️ Bloque {i}-{i+300} sin nuevos registros.")
            await asyncio.sleep(0.01)

if __name__ == "__main__":
    asyncio.run(ejecutar_ultimo_intento())