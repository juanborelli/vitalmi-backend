import re
from app.core.supabase_client import supabase

def clasificar_y_limpiar_numeros(cadena_telefonos, whatsapp_actual=None):
    """
    Separa la cadena de teléfonos en:
    - telefono_institucional (fijo principal)
    - telefono_alterno (fijo secundario)
    - whatsapp (móvil validado)
    """
    if not cadena_telefonos or cadena_telefonos in ["No disponible", "None", ""]:
        return "No disponible", None, whatsapp_actual

    piezas = re.split(r'[/,;\n]+', str(cadena_telefonos))
    fijos = []
    moviles = []

    for p in piezas:
        limpio = re.sub(r'\D', '', p)
        if len(limpio) == 10 and limpio.startswith(('809', '829', '849')):
            num_fmt = f"{limpio[:3]}-{limpio[3:6]}-{limpio[6:]}"
            moviles.append(f"1{limpio}")
            fijos.append(num_fmt)
        elif len(limpio) == 11 and limpio.startswith('1') and limpio[1:].startswith(('809', '829', '849')):
            num_10 = limpio[1:]
            num_fmt = f"{num_10[:3]}-{num_10[3:6]}-{num_10[6:]}"
            moviles.append(limpio)
            fijos.append(num_fmt)

    fijos = list(dict.fromkeys(fijos))
    moviles = list(dict.fromkeys(moviles))

    tel_inst = fijos[0] if len(fijos) > 0 else "No disponible"
    tel_alt = fijos[1] if len(fijos) > 1 else None
    
    ws_final = whatsapp_actual
    if not ws_final and len(moviles) > 0:
        ws_final = moviles[0]

    return tel_inst, tel_alt, ws_final

def estructurar_telefonos_master():
    print("=== 🚀 ESTRUCTURANDO TELÉFONOS EN VITALMI_DIRECTORIO_MASTER ===")
    inicio, paso = 0, 500
    total_actualizados = 0

    while True:
        res = supabase.table("vitalmi_directorio_master").select("id, telefonos, whatsapp").range(inicio, inicio + paso - 1).execute()
        if not res.data:
            break

        for reg in res.data:
            reg_id = reg.get("id")
            tels_raw = reg.get("telefonos")
            ws_actual = reg.get("whatsapp")

            tel_inst, tel_alt, ws_final = clasificar_y_limpiar_numeros(tels_raw, ws_actual)

            # Actualización directa por ID para no violar restricciones NOT NULL de otras columnas
            supabase.table("vitalmi_directorio_master").update({
                "telefono_institucional": tel_inst,
                "telefono_alterno": tel_alt,
                "whatsapp": ws_final
            }).eq("id", reg_id).execute()

            total_actualizados += 1

        print(f"   ✅ Lote procesado. Total hasta el momento: {total_actualizados}")
        inicio += paso

    print(f"\n🎉 ¡PROCESO COMPLETADO! Se reestructuraron {total_actualizados} registros con éxito.")

if __name__ == "__main__":
    estructurar_telefonos_master()