from app.core.supabase_client import supabase

MAPEO_TABLAS = {
    "CENTRO DIAGNOSTICOS": "centro_diagnosticos_mapfre",
    "CENTRO ESPECIALIZADO": "centro_especializado_mapfre",
    "CLINICA": "clinica_mapfre",
    "DENTALES": "dentales_mapfre",
    "FARMACIA": "farmacia_mapfre",
    "LABORATORIO": "laboratorio_mapfre",
    "MEDICO": "medico_mapfre"
}

def migrar_directorio_mapfre():
    print("=== 🚀 MIGRANDO PRESTADORES DE MAPFRE A SUS 7 TABLAS OFICIALES ===")
    
    # 1. Migrar Médicos de Mapfre
    inicio = 0
    paso = 1000
    total_medicos = 0
    while True:
        res = supabase.table("medicos").select("*").eq("ars", "Mapfre Salud ARS").range(inicio, inicio + paso - 1).execute()
        if not res.data:
            break
        supabase.table("medico_mapfre").upsert(res.data, on_conflict="id").execute()
        total_medicos += len(res.data)
        inicio += paso
    print(f"✅ [MEDICO_MAPFRE] Guardados {total_medicos} médicos.")

    # 2. Migrar No Médicos de Mapfre a sus categorías oficiales
    tablas_genericas = ["clinicas", "farmacias", "laboratorios", "odontologos"]
    for t_origen in tablas_genericas:
        res = supabase.table(t_origen).select("*").eq("ars", "Mapfre Salud ARS").execute()
        if not res.data:
            continue
        
        for reg in res.data:
            tipo = str(reg.get("tipo_prestador") or "").upper().strip()
            
            # Clasificación hacia la tabla exacta de Mapfre
            if "DIAGNOSTICO" in tipo:
                t_destino = "centro_diagnosticos_mapfre"
            elif "ESPECIALIZADO" in tipo:
                t_destino = "centro_especializado_mapfre"
            elif "FARMACIA" in tipo:
                t_destino = "farmacia_mapfre"
            elif "LABORATORIO" in tipo:
                t_destino = "laboratorio_mapfre"
            elif "DENTAL" in tipo or "ODONTOL" in tipo:
                t_destino = "dentales_mapfre"
            else:
                t_destino = "clinica_mapfre"

            supabase.table(t_destino).upsert(reg, on_conflict="id").execute()

if __name__ == "__main__":
    migrar_directorio_mapfre()