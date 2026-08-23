import json
from dotenv import load_dotenv
from app.core.supabase import obtener_cliente_supabase

load_dotenv(override=True)
supabase = obtener_cliente_supabase()

if not supabase:
    print("❌ No hay conexión a Supabase")
    exit()

def auditar_especialidades_ginecologia():
    print("🔍 AUDITANDO CAMPOS DE ESPECIALIDAD EN 'vitalmi_directorio_master'...\n")

    # Traer todos los registros de San Cristóbal para inspeccionar campos
    res = (
        supabase.table("vitalmi_directorio_master")
        .select("nombre, especialidad, especialidad_medico, especialidad_clinica, centro_medico, provincia")
        .eq("provincia", "San Cristóbal")
        .execute()
    )

    total_sc = len(res.data)
    print(f"📦 Total registros en San Cristóbal: {total_sc}")

    # Filtrar coincidencias flexibles de Ginecología en San Cristóbal
    gineco_sc = [
        r for r in res.data 
        if "GINEC" in (r.get("especialidad") or "").upper()
        or "GINEC" in (r.get("especialidad_medico") or "").upper()
        or "GINEC" in (r.get("especialidad_clinica") or "").upper()
    ]

    print(f"📊 Ginecólogos/Ginecobstetras encontrados en San Cristóbal: {len(gineco_sc)}\n")

    if gineco_sc:
        print("📋 Muestra de Ginecólogos encontrados:")
        print(json.dumps(gineco_sc[:5], indent=2, ensure_ascii=False))

if __name__ == "__main__":
    auditar_especialidades_ginecologia()