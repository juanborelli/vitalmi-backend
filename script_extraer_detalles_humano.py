import asyncio
import aiohttp
import re
import pandas as pd
from app.core.supabase_client import supabase

URL_AJAX = "https://humanoseguros.com/wp-admin/admin-ajax.php"
NONCE_ACTIVO = "4ba3d4cba0"

HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'es,es-419;q=0.9,en;q=0.8',
    'Origin': 'https://humanoseguros.com',
    'Referer': 'https://humanoseguros.com/directorio-medico/',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def extraer_whatsapp(lista_telefonos):
    for tel in lista_telefonos:
        limpio = re.sub(r'\D', '', str(tel))
        if len(limpio) == 10 and limpio.startswith(('809', '829', '849')):
            return f"1{limpio}"
        elif len(limpio) == 11 and limpio.startswith('1') and limpio[1:].startswith(('809', '829', '849')):
            return limpio
    return None

def extraer_todos_los_telefonos(p):
    tels = []
    fuentes_tel = [p.get("telefonos"), p.get("telefono"), p.get("telefonosPrestador"), p.get("contacto")]
    for f in fuentes_tel:
        if isinstance(f, list):
            for item in f:
                if isinstance(item, dict):
                    val = item.get("numero") or item.get("telefono") or item.get("num")
                    if val: tels.append(str(val).strip())
                elif isinstance(item, str) and item.strip():
                    tels.append(item.strip())
        elif isinstance(f, str) and f.strip():
            tels.append(f.strip())

    dirs = p.get("direcciones") or p.get("direccion") or []
    if isinstance(dirs, list):
        for d in dirs:
            if isinstance(d, dict):
                t_dir = d.get("telefonos") or d.get("telefono")
                if isinstance(t_dir, list):
                    for t in t_dir:
                        val = t.get("numero") if isinstance(t, dict) else str(t)
                        if val: tels.append(str(val).strip())
                elif isinstance(t_dir, str) and t_dir.strip():
                    tels.append(t_dir.strip())

    return list(dict.fromkeys(tels))

async def obtener_detalle_prestador(session, codigo_prestador, semaphore):
    async with semaphore:
        data = aiohttp.FormData()
        data.add_field('action', 'dirmed_proxy')
        data.add_field('_nonce', NONCE_ACTIVO)
        data.add_field('endpoint', 'datos-prestador')
        data.add_field('method', 'POST')
        data.add_field('body', f'{{"codigoPrestador":"{codigo_prestador}","tipoPrestador":"NO-MEDICO"}}')

        try:
            async with session.post(URL_AJAX, headers=HEADERS, data=data, timeout=10) as res:
                if res.status == 200:
                    res_json = await res.json()
                    prestador = res_json.get("prestador") or res_json.get("datos")
                    if prestador and prestador.get("nombre"):
                        return prestador
        except Exception:
            pass
        return None

def clasificar_y_guardar_no_medicos(detalles_lista):
    clinicas_dict, farmacias_dict, laboratorios_dict, odontologos_dict = {}, {}, {}, {}

    for p in detalles_lista:
        try:
            codigo = str(p.get("codigo") or p.get("codigoPrestador") or "").strip()
            nombre = str(p.get("nombre") or "").strip()
            if not nombre or not codigo:
                continue

            pres_id = f"HUM-NOMED-{codigo}"
            categoria = str(p.get("categoria") or p.get("tipoCentroMedico") or "PRESTADOR").upper().strip()

            dirs = p.get("direcciones") or p.get("direccion") or []
            direccion, ciudad, sector = "No especificada", "No especificada", "No especificado"

            if isinstance(dirs, list) and len(dirs) > 0:
                primer_dir = dirs[0] if isinstance(dirs[0], dict) else {"direccion": str(dirs[0])}
                direccion = str(primer_dir.get("direccion") or "No especificada").strip()
                ciudad = str(primer_dir.get("ciudad") or primer_dir.get("provincia") or "No especificada").strip()
                sector = str(primer_dir.get("sector") or "No especificado").strip()
            elif isinstance(dirs, str) and dirs:
                direccion = dirs.strip()

            if any(pais in direccion.upper() for pais in ["PUERTO RICO", "MIAMI", "FLORIDA", "SPAIN", "ESPANA", "USA"]):
                continue

            if ciudad == "No especificada" and "," in direccion:
                ciudad = direccion.split(",")[-1].strip()

            tels = extraer_todos_los_telefonos(p)
            tel_str = ", ".join(tels) if tels else "No disponible"
            whatsapp_num = extraer_whatsapp(tels)

            planes = p.get("plan") or p.get("planes") or []
            lista_planes = []
            if isinstance(planes, list):
                for pl in planes:
                    nom = pl.get("nombre") if isinstance(pl, dict) else str(pl)
                    if nom and str(nom).strip():
                        lista_planes.append(str(nom).strip())
            planes_str = ", ".join(lista_planes) if lista_planes else "Todos los planes"

            registro = {
                "id": pres_id,
                "nombre": nombre,
                "tipo_prestador": categoria,
                "direccion": direccion,
                "ciudad_provincia": ciudad if ciudad != "No especificada" else "República Dominicana",
                "sector": sector,
                "telefonos": tel_str,
                "whatsapp": whatsapp_num,
                "planes_aceptados": planes_str,
                "ars": "ARS Humano"
            }

            nombre_upper = nombre.upper()
            if "FARMACIA" in nombre_upper or "FARMACIA" in categoria:
                farmacias_dict[pres_id] = registro
            elif "LABORATORIO" in nombre_upper or "DIAGNOSTICO" in nombre_upper or "LABORATORIO" in categoria:
                laboratorios_dict[pres_id] = registro
            elif "ODONTOLOG" in nombre_upper or "DENTAL" in nombre_upper or "ODONTOL" in categoria:
                odontologos_dict[pres_id] = registro
            else:
                clinicas_dict[pres_id] = registro

        except Exception:
            continue

    def guardar_tabla(tabla_nombre, registros_dict):
        registros = list(registros_dict.values())
        if not registros:
            return
        try:
            supabase.table(tabla_nombre).delete().eq("ars", "ARS Humano").execute()
            supabase.table(tabla_nombre).upsert(registros, on_conflict="id").execute()
            print(f"   ✅ [{tabla_nombre.upper()}] Guardados {len(registros)} registros enriquecidos.")
        except Exception as e:
            print(f"   ❌ Error guardando en {tabla_nombre}: {e}")

    guardar_tabla("clinicas_humano", clinicas_dict)
    guardar_tabla("farmacias_humano", farmacias_dict)
    guardar_tabla("laboratorios_humano", laboratorios_dict)
    guardar_tabla("odontologos_humano", odontologos_dict)

async def ejecutar_extraccion_no_medicos_humano():
    print(f"=== 🚀 REINICIANDO EXTRACCIÓN DETALLADA DE HUMANO (NONCE: {NONCE_ACTIVO}) ===")
    
    try:
        df = pd.read_csv("DIRECTORIO_SALUD_MAPFRE_HUMANO.csv")
        df_nomed = df[df['TipoPrestador'] == 'NO-MEDICO']
        codigos_reales = df_nomed['CodigoPrestador'].dropna().astype(int).unique().tolist()
        print(f"📋 Cargados {len(codigos_reales)} códigos no médicos reales de Humano.")
    except Exception:
        codigos_reales = list(range(1, 2500))

    semaphore = asyncio.Semaphore(15)
    async with aiohttp.ClientSession() as session:
        tasks = [obtener_detalle_prestador(session, cod, semaphore) for cod in codigos_reales]
        resultados = await asyncio.gather(*tasks)
        
        validos = [r for r in resultados if r is not None]
        if validos:
            clasificar_y_guardar_no_medicos(validos)

if __name__ == "__main__":
    asyncio.run(ejecutar_extraccion_no_medicos_humano())