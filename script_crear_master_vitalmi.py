import re
from app.core.supabase_client import supabase

def normalizar_nombre(nombre):
    """Limpia tildes, caracteres especiales y prefijos para matching exacto."""
    n = str(nombre or "").upper().strip()
    n = re.sub(r'^(DR\.|DRA\.|LIC\.|ING\.|SR\.|SRA\.)\s+', '', n)
    n = re.sub(r'[^A-Z0-9\s]', '', n)
    return " ".join(n.split())

def consolidar_directorio_master():
    print("=== 🚀 CREANDO Y CONSOLIDANDO VITALMI_DIRECTORIO_MASTER ===")
    
    # 1. Definir mapeo de tablas origen -> tipo de prestador estandarizado
    fuentes = [
        ("medicos_humano", "MEDICO", "ARS Humano"),
        ("medico_mapfre", "MEDICO", "Mapfre Salud ARS"),
        ("clinicas_humano", "CLINICA", "ARS Humano"),
        ("clinica_mapfre", "CLINICA", "Mapfre Salud ARS"),
        ("farmacias_humano", "FARMACIA", "ARS Humano"),
        ("farmacia_mapfre", "FARMACIA", "Mapfre Salud ARS"),
        ("laboratorios_humano", "LABORATORIO", "ARS Humano"),
        ("laboratorio_mapfre", "LABORATORIO", "Mapfre Salud ARS"),
        ("odontologos_humano", "ODONTOLOGO", "ARS Humano"),
        ("dentales_mapfre", "ODONTOLOGO", "Mapfre Salud ARS"),
        ("centro_diagnosticos_mapfre", "CENTRO DIAGNOSTICO", "Mapfre Salud ARS"),
        ("centro_especializado_mapfre", "CENTRO ESPECIALIZADO", "Mapfre Salud ARS")
    ]

    master_dict = {}

    for tabla_origen, tipo_std, ars_nombre in fuentes:
        print(f"📦 Procesando tabla '{tabla_origen}'...")
        inicio, paso = 0, 1000
        
        while True:
            try:
                res = supabase.table(tabla_origen).select("*").range(inicio, inicio + paso - 1).execute()
                if not res.data:
                    break
                
                for r in res.data:
                    nombre_orig = str(r.get("nombre") or "").strip()
                    if not nombre_orig:
                        continue

                    # Clave de deduplicación basada en nombre normalizado + tipo
                    clave_dedup = f"{tipo_std}_{normalizar_nombre(nombre_orig)}"
                    
                    # Datos del registro
                    especialidad = str(r.get("especialidad") or "General").strip()
                    centro = str(r.get("centro_medico") or "No especificado").strip()
                    direccion = str(r.get("direccion") or "No especificada").strip()
                    ciudad = str(r.get("ciudad_provincia") or "República Dominicana").strip()
                    sector = str(r.get("sector") or "No especificado").strip()
                    telefonos = str(r.get("telefonos") or "No disponible").strip()
                    whatsapp = r.get("whatsapp")
                    planes = str(r.get("planes_aceptados") or "Todos los planes").strip()

                    if clave_dedup in master_dict:
                        # Si ya existe por otra ARS, fusionamos la cobertura
                        elem = master_dict[clave_dedup]
                        if ars_nombre not in elem["aseguradoras"]:
                            elem["aseguradoras"].append(ars_nombre)
                        
                        # Conservar WhatsApp si el nuevo registro lo tiene y el anterior no
                        if not elem.get("whatsapp") and whatsapp:
                            elem["whatsapp"] = whatsapp
                        
                        # Conservar la dirección/teléfono con más detalle
                        if len(telefonos) > len(elem.get("telefonos") or "") and telefonos != "No disponible":
                            elem["telefonos"] = telefonos
                        if len(direccion) > len(elem.get("direccion") or "") and direccion != "No especificada":
                            elem["direccion"] = direccion
                    else:
                        master_dict[clave_dedup] = {
                            "id": f"VTL-{len(master_dict) + 1:06d}",
                            "nombre": nombre_orig,
                            "tipo_prestador": tipo_std,
                            "especialidad": especialidad,
                            "centro_medico": centro,
                            "direccion": direccion,
                            "ciudad_provincia": ciudad,
                            "sector": sector,
                            "telefonos": telefonos,
                            "whatsapp": whatsapp,
                            "planes_aceptados": planes,
                            "aseguradoras": [ars_nombre]
                        }

                inicio += paso
            except Exception as e:
                print(f"   ⚠️ Nota en {tabla_origen}: {e}")
                break

    registros_master = list(master_dict.values())
    print(f"\n🎯 Total de registros consolidados y deduplicados: {len(registros_master)}")

    # 2. Reemplazo limpio en la tabla maestra
    print("💾 Guardando en 'vitalmi_directorio_master'...")
    supabase.table("vitalmi_directorio_master").delete().neq("id", "0").execute()
    
    for i in range(0, len(registros_master), 500):
        bloque = registros_master[i:i+500]
        supabase.table("vitalmi_directorio_master").upsert(bloque, on_conflict="id").execute()
        print(f"   ✅ Lote {i // 500 + 1} guardado ({len(bloque)} registros).")

    print("\n🎉 ¡DIRECTORIO MASTER VITALMI CREADO CON ÉXITO!")

if __name__ == "__main__":
    consolidar_directorio_master()