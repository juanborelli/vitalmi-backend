from app.core.supabase_client import supabase

def migrar_tabla(tabla_origen, tabla_destino, tipo_default="MEDICO"):
    print(f"\n📦 Migrando datos desde '{tabla_origen}' hacia '{tabla_destino}'...")
    
    inicio = 0
    paso = 1000
    total_copiados = 0
    
    while True:
        res = supabase.table(tabla_origen).select("*").eq("ars", "ARS Humano").range(inicio, inicio + paso - 1).execute()
        if not res.data:
            break
        
        lote_limpio = []
        for reg in res.data:
            elem = dict(reg)
            # Asegurar campo tipo_prestador
            elem["tipo_prestador"] = elem.get("tipo_prestador") or tipo_default
            lote_limpio.append(elem)

        try:
            supabase.table(tabla_destino).upsert(lote_limpio, on_conflict="id").execute()
            total_copiados += len(lote_limpio)
        except Exception as e:
            # Fallback en caso de que la columna tipo_prestador no esté sincronizada en la API
            if "tipo_prestador" in str(e):
                for elem in lote_limpio:
                    elem.pop("tipo_prestador", None)
                supabase.table(tabla_destino).upsert(lote_limpio, on_conflict="id").execute()
                total_copiados += len(lote_limpio)
            else:
                raise e

        inicio += paso

    print(f"   ✅ [{tabla_destino.upper()}] {total_copiados} registros migrados con éxito.")

if __name__ == "__main__":
    print("=== 🚀 INICIANDO MIGRACIÓN DEL DIRECTORIO HUMANO ===")
    
    migrar_tabla("medicos", "medicos_humano", tipo_default="MEDICO")
    migrar_tabla("clinicas", "clinicas_humano", tipo_default="CLINICA Y CENTRO DE SALUD")
    migrar_tabla("farmacias", "farmacias_humano", tipo_default="FARMACIA")
    migrar_tabla("laboratorios", "laboratorios_humano", tipo_default="LABORATORIO")
    migrar_tabla("odontologos", "odontologos_humano", tipo_default="CENTRO ODONTOLOGICO")
    
    print("\n🎉 ¡DIRECTORIO HUMANO ORGANIZADO CON ÉXITO!")