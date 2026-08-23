import asyncio
import aiohttp
import re
from app.core.supabase_client import supabase

URL_AJAX = "https://humanoseguros.com/wp-admin/admin-ajax.php"

HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'es,es-419;q=0.9,en;q=0.8',
    'Origin': 'https://humanoseguros.com',
    'Referer': 'https://humanoseguros.com/directorio-medico/',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def extraer_whatsapp(lista_telefonos):
    """Detecta el primer número celular dominicano (809/829/849) para WhatsApp."""
    for tel in lista_telefonos:
        limpio = re.sub(r'\D', '', str(tel))
        if len(limpio) == 10 and limpio.startswith(('809', '829', '849')):
            return f"1{limpio}"
        elif len(limpio) == 11 and limpio.startswith('1') and limpio[1:].startswith(('809', '829', '849')):
            return limpio
    return None

async def consultar_prestador_no_medico(session, codigo_prestador, semaphore):
    """Consulta el endpoint datos-prestador para tipoPrestador NO-MEDICO."""
    async with semaphore:
        data = aiohttp.FormData()
        data.add_field('action', 'dirmed_proxy')
        data.add_field('_nonce', '4974e2c9de')
        data.add_field('endpoint', 'datos-prestador')
        data.add_field('method', 'POST')
        data.add_field('body', f'{{"codigoPrestador":"{codigo_prestador}","tipoPrestador":"NO-MEDICO"}}')

        try:
            async with session.post(URL_AJAX, headers=HEADERS, data=data, timeout=8) as res:
                if res.status == 200:
                    res_json = await res.json()
                    prestador = res_json.get("prestador")
                    if prestador and prestador.get("nombre"):
                        return prestador
        except Exception:
            pass
        return None

def clasificar_y_guardar_lote(prestadores_lista, tamano_lote=200):
    """Clasifica los prestadores recibidos y los guarda en sus tablas correspondientes."""
    clinicas_dict = {}
    farmacias_dict = {}
    laboratorios_dict = {}
    odontologos_dict = {}

    for p in prestadores_lista:
        try:
            codigo = str(p.get("codigo") or p.get("codigoPrestador") or "").strip()
            nombre = str(p.get("nombre") or "").strip()
            if not nombre or not codigo:
                continue

            pres_id = f"HUM-NOMED-{codigo}"
            
            # Datos del tipo y categoría
            categoria = str(p.get("categoria") or "").upper().strip()

            # Dirección y Ciudad
            dirs = p.get("direcciones") or []
            direccion = "No especificada"
            if isinstance(dirs, list) and len(dirs) > 0:
                direccion = dirs[0].get("direccion", "No especificada").strip() if isinstance(dirs[0], dict) else str(dirs[0])

            ciudad = "No especificada"
            if "," in direccion:
                ciudad = direccion.split(",")[-1].strip()

            # Teléfonos y WhatsApp
            phones_list = p.get("telefonos") or []
            tels = []
            if isinstance(phones_list, list):
                for t in phones_list:
                    val = t.get("numero") if isinstance(t, dict) else str(t)
                    if val and str(val).strip():
                        tels.append(str(val).strip())
            tel_str = " / ".join(list(dict.fromkeys(tels))) if tels else "No disponible"
            whatsapp_num = extraer_whatsapp(tels)

            # Planes aceptados
            planes = p.get("plan") or []
            lista_planes = []
            if isinstance(planes, list):
                for pl in planes:
                    nom = pl.get("nombre") if isinstance(pl, dict) else str(pl)
                    if nom and str(nom).strip():
                        lista_planes.append(str(nom).strip())
            planes_str = " / ".join(lista_planes) if lista_planes else "Todos los planes"

            registro = {
                "id": pres_id,
                "nombre": nombre,
                "tipo_prestador": categoria or "PRESTADOR NO MEDICO",
                "direccion": direccion,
                "ciudad_provincia": ciudad,
                "sector": "No especificado",
                "telefonos": tel_str,
                "whatsapp": whatsapp_num,
                "planes_aceptados": planes_str,
                "ars": "ARS Humano"
            }

            # Clasificación inteligente por tipo o palabras clave en el nombre
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
        
        for i in range(0, len(registros), tamano_lote):
            lote = registros[i:i + tamano_lote]
            try:
                supabase.table(tabla_nombre).upsert(lote, on_conflict="id").execute()
                print(f"   💾 [{tabla_nombre.upper()}] Guardado lote de {len(lote)} registros.")
            except Exception as e:
                print(f"   ❌ Error guardando en {tabla_nombre}: {e}")

    guardar_tabla("clinicas", clinicas_dict)
    guardar_tabla("farmacias", farmacias_dict)
    guardar_tabla("laboratorios", laboratorios_dict)
    guardar_tabla("odontologos", odontologos_dict)

async def escaneo_prestadores_no_medicos(inicio=5000, fin=50000, tamano_bloque=200):
    print(f"=== 🚀 INICIANDO ESCANEO PRESTADORES NO MÉDICOS ({inicio} a {fin}) ===")
    semaphore = asyncio.Semaphore(15)
    
    async with aiohttp.ClientSession() as session:
        for bloque_inicio in range(inicio, fin, tamano_bloque):
            bloque_fin = min(bloque_inicio + tamano_bloque, fin)
            print(f"\n🔎 Escaneando prestadores no médicos: {bloque_inicio} -> {bloque_fin}...")
            
            tasks = [consultar_prestador_no_medico(session, i, semaphore) for i in range(bloque_inicio, bloque_fin)]
            resultados = await asyncio.gather(*tasks)
            
            validos = [r for r in resultados if r is not None]
            print(f"   🎯 Prestadores válidos encontrados: {len(validos)}")
            
            if validos:
                clasificar_y_guardar_lote(validos)
            
            await asyncio.sleep(0.2)

if __name__ == "__main__":
    # Escaneo amplio para capturar el 100% de clínicas, farmacias, laboratorios y dentales
    asyncio.run(escaneo_prestadores_no_medicos(5000, 50000))