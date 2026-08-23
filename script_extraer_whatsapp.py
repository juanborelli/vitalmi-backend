import re
from app.core.supabase_client import supabase

def extraer_primer_celular_rd(cadena_telefonos):
    """
    Analiza cadenas con múltiples teléfonos separados por '/', ',', ';' o espacios
    y extrae el primer celular válido de República Dominicana (809, 829, 849).
    """
    if not cadena_telefonos or cadena_telefonos == "No disponible":
        return None
    
    # Separar la cadena por delimitadores comunes
    piezas = re.split(r'[/,;\s]+', str(cadena_telefonos))
    for p in piezas:
        limpio = re.sub(r'\D', '', p)
        # Formato de 10 dígitos (ej: 8091234567)
        if len(limpio) == 10 and limpio.startswith(('809', '829', '849')):
            return f"1{limpio}"
        # Formato de 11 dígitos con código de país (ej: 18091234567)
        elif len(limpio) == 11 and limpio.startswith('1') and limpio[1:].startswith(('809', '829', '849')):
            return limpio
    return None

def actualizar_whatsapp_en_tabla(tabla_nombre):
    print(f"\n🔍 Procesando extracción de WhatsApp en '{tabla_nombre}'...")
    inicio, paso = 0, 1000
    actualizados = 0

    while True:
        res = supabase.table(tabla_nombre).select("id, telefonos, whatsapp").range(inicio, inicio + paso - 1).execute()
        if not res.data:
            break

        lote_actualizar = []
        for reg in res.data:
            tels = reg.get("telefonos")
            ws_actual = reg.get("whatsapp")
            ws_detectado = extraer_primer_celular_rd(tels)

            # Si detectamos un WhatsApp y no estaba registrado o era diferente, lo preparamos para actualizar
            if ws_detectado and ws_detectado != ws_actual:
                lote_actualizar.append({
                    "id": reg["id"],
                    "whatsapp": ws_detectado
                })

        if lote_actualizar:
            supabase.table(tabla_nombre).upsert(lote_actualizar, on_conflict="id").execute()
            actualizados += len(lote_actualizar)

        inicio += paso

    print(f"   ✅ [{tabla_nombre.upper()}] Se identificaron y guardaron {actualizados} números de WhatsApp.")

def ejecutar_proceso_whatsapp():
    print("=== 🚀 INICIANDO EXTRACCIÓN Y SINCRONIZACIÓN DE WHATSAPP ===")

    # 1. Procesar primero los directorios de origen (Humano y Mapfre)
    tablas_medicos = ["medicos_humano", "medico_mapfre"]
    for t in tablas_medicos:
        actualizar_whatsapp_en_tabla(t)

    # 2. Re-ejecutar el barrido en la tabla maestra consolidada de VitalMi
    print("\n🔄 Sincronizando números de WhatsApp hacia 'vitalmi_directorio_master'...")
    actualizar_whatsapp_en_tabla("vitalmi_directorio_master")

    print("\n🎉 ¡PROCESO COMPLETADO CON ÉXITO!")

if __name__ == "__main__":
    ejecutar_proceso_whatsapp()