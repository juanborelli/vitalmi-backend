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
            return f"1{limpio}"  # Formato internacional para Evolution API
        elif len(limpio) == 11 and limpio.startswith('1') and limpio[1:].startswith(('809', '829', '849')):
            return limpio
    return None

async def obtener_lista_completa_humano():
    """Llama al endpoint masivo 'prestadores' de ARS Humano."""
    data = aiohttp.FormData()
    data.add_field('action', 'dirmed_proxy')
    data.add_field('_nonce', '4974e2c9de')
    data.add_field('endpoint', 'prestadores')
    data.add_field('method', 'POST')
    data.add_field('body', '{"tipoPrestador":"MEDICO","tipoCentroMedicoId":1}')

    print("🚀 Solicitando listado masivo de médicos a ARS Humano...")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(URL_AJAX, headers=HEADERS, data=data, timeout=30) as res:
                if res.status == 200:
                    res_json = await res.json()
                    if isinstance(res_json, dict) and "prestadores" in res_json:
                        return res_json.get("prestadores", [])
                    elif isinstance(res_json, list):
                        return res_json
                    elif isinstance(res_json, dict) and "respuesta" in res_json:
                        return res_json.get("prestadores", res_json.get("datos", []))
        except Exception as e:
            print(f"❌ Error al consultar la API masiva de Humano: {e}")
        return []

def guardar_lotes_en_supabase(prestadores_lista, tamano_lote=200):
    """Procesa y guarda los médicos en Supabase divididos en lotes."""
    total = len(prestadores_lista)
    print(f"📦 Total de médicos recibidos para procesar: {total}")
    
    medicos_dict = {}
    
    for idx, p in enumerate(prestadores_lista):
        try:
            codigo = str(p.get("codigo") or p.get("codigoPrestador") or idx + 1).strip()
            nombre = str(p.get("nombre") or p.get("nombrePrestador") or "").strip()
            if not nombre:
                continue

            med_id = f"HUM-{codigo}"
            if med_id in medicos_dict:
                continue

            # Especialidad
            specs = p.get("especialidad") or p.get("especialidades") or []
            especialidad = "General"
            if isinstance(specs, list) and len(specs) > 0:
                especialidad = specs[0].get("nombre", "General").strip() if isinstance(specs[0], dict) else str(specs[0])
            elif isinstance(specs, str) and specs:
                especialidad = specs.strip()

            # Centro Médico
            centros = p.get("centroMedico") or p.get("centrosMedicos") or []
            centro_medico = "Consulta Privada"
            if isinstance(centros, list) and len(centros) > 0:
                centro_medico = centros[0].get("nombre", "Consulta Privada").strip() if isinstance(centros[0], dict) else str(centros[0])
            elif isinstance(centros, str) and centros:
                centro_medico = centros.strip()

            # Dirección y Ciudad
            dirs = p.get("direcciones") or p.get("direccion") or []
            direccion = "No especificada"
            if isinstance(dirs, list) and len(dirs) > 0:
                direccion = dirs[0].get("direccion", "No especificada").strip() if isinstance(dirs[0], dict) else str(dirs[0])
            elif isinstance(dirs, str) and dirs:
                direccion = dirs.strip()

            ciudad = str(p.get("ciudad") or p.get("provincia") or "No especificada").strip()
            if ciudad == "No especificada" and "," in direccion:
                ciudad = direccion.split(",")[-1].strip()

            # Teléfonos y WhatsApp
            telefonos_raw = p.get("telefonos") or p.get("telefono") or []
            tels = []
            if isinstance(telefonos_raw, list):
                for t in telefonos_raw:
                    val = t.get("numero") if isinstance(t, dict) else str(t)
                    if val and str(val).strip():
                        tels.append(str(val).strip())
            elif isinstance(telefonos_raw, str) and telefonos_raw:
                tels = [telefonos_raw.strip()]

            tel_str = " / ".join(list(dict.fromkeys(tels))) if tels else "No disponible"
            whatsapp_num = extraer_whatsapp(tels)

            # Planes aceptados
            planes = p.get("plan") or p.get("planes") or []
            lista_planes = []
            if isinstance(planes, list):
                for pl in planes:
                    nom = pl.get("nombre") if isinstance(pl, dict) else str(pl)
                    if nom and str(nom).strip():
                        lista_planes.append(str(nom).strip())
            planes_str = " / ".join(lista_planes) if lista_planes else "Todos los planes"

            medicos_dict[med_id] = {
                "id": med_id,
                "nombre": nombre,
                "especialidad": especialidad,
                "centro_medico": centro_medico,
                "direccion": direccion,
                "telefonos": tel_str,
                "whatsapp": whatsapp_num,
                "ciudad_provincia": ciudad,
                "sector": str(p.get("sector") or "No especificado").strip(),
                "planes_aceptados": planes_str,
                "tipo_prestador": "MEDICO",
                "ars": "ARS Humano"
            }
        except Exception:
            continue

    registros_totales = list(medicos_dict.values())

    if not registros_totales:
        print("⚠️ No se pudieron formatear los registros correctamente.")
        return

    print(f"💾 Guardando {len(registros_totales)} registros limpios en Supabase en lotes...")
    
    for i in range(0, len(registros_totales), tamano_lote):
        lote = registros_totales[i:i + tamano_lote]
        try:
            supabase.table("medicos").upsert(lote, on_conflict="id").execute()
            print(f"   ✅ Lote {i // tamano_lote + 1} guardado ({len(lote)} médicos).")
        except Exception as e:
            print(f"   ❌ Error guardando lote {i // tamano_lote + 1}: {e}")

    print("\n🎉 ¡PROCESO DE ARS HUMANO COMPLETADO CON ÉXITO!")

if __name__ == "__main__":
    lista = asyncio.run(obtener_lista_completa_humano())
    if lista:
        guardar_lotes_en_supabase(lista)
    else:
        print("❌ No se obtuvieron registros. Revisa el _nonce o las cookies.")