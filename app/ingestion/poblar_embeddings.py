import os
import time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client, Client

# Cargar variables de entorno desde el archivo .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# ==========================================
# CONFIGURACIÓN DE CREDENCIALES Y CLIENTES
# ==========================================
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://vpkbflsgfalydnfppgwz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_4viWrDy4LWSH8bskjDUevA__MjMPyiD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Inicializar clientes oficiales
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Parámetros operativos
BATCH_SIZE = 50  # Lotes para procesar y optimizar el rendimiento
EMBEDDING_MODEL = "text-embedding-3-small"  # Modelo eficiente y económico para embeddings

def construir_texto_para_vector(record: dict) -> str:
    """
    Construye un texto enriquecido y estructurado a partir de los campos 
    consolidados para que el embedding de OpenAI capture el contexto médico ideal.
    """
    nombre = record.get("nombre") or ""
    tipo = record.get("tipo_prestador") or ""
    especialidades = ", ".join(record.get("especialidades_consolidadas") or [])
    centro = record.get("centro_medico") or ""
    provincia = record.get("provincia") or ""
    sector = record.get("sector") or ""
    aseguradoras = ", ".join(record.get("aseguradoras") or [])

    texto_enriquecido = (
        f"Prestador: {nombre}. "
        f"Tipo: {tipo}. "
        f"Especialidades: {especialidades}. "
        f"Centro Médico: {centro}. "
        f"Ubicación: {sector}, {provincia}. "
        f"Aseguradoras que acepta: {aseguradoras}."
    )
    return texto_enriquecido

def generar_embedding(texto: str) -> list:
    """
    Genera el vector de embedding utilizando la API de OpenAI.
    """
    response = openai_client.embeddings.create(
        input=[texto],
        model=EMBEDDING_MODEL
    )
    return response.data[0].embedding

def poblar_embeddings():
    print("🚀 Iniciando proceso de vectorización para VitalMi/Gema...")

    # 1. Consultar cuántos registros faltan por vectorizar
    count_response = supabase.table("vitalmi_directorio_master") \
        .select("id", count="exact") \
        .is_("embedding", "null") \
        .execute()
    
    total_pendientes = count_response.count
    if not total_pendientes or total_pendientes == 0:
        print("✅ ¡Excelente noticia! No hay registros pendientes de vectorizar. El directorio está al 100%.")
        return

    print(f"📊 Registros totales pendientes de vectorizar: {total_pendientes}")

    procesados = 0

    while True:
        # 2. Traer un lote de registros pendientes
        response = supabase.table("vitalmi_directorio_master") \
            .select("id, nombre, tipo_prestador, especialidades_consolidadas, centro_medico, provincia, sector, aseguradoras") \
            .is_("embedding", "null") \
            .limit(BATCH_SIZE) \
            .execute()
        
        registros = response.data
        if not registros:
            break

        print(f"\n🔄 Procesando lote de {len(registros)} registros...")

        for reg in registros:
            try:
                # Construir el texto base para la IA
                texto_vector = construir_texto_para_vector(reg)

                # Obtener el embedding de OpenAI
                vector = generar_embedding(texto_vector)

                # Actualizar el registro en Supabase con su nuevo embedding
                supabase.table("vitalmi_directorio_master") \
                    .update({"embedding": vector}) \
                    .eq("id", reg["id"]) \
                    .execute()

                procesados += 1
                print(f"   [OK] Vectorizado ({procesados}/{total_pendientes}): {reg.get('nombre')} [{reg.get('id')}]")

                # Pequeña pausa para respetar los rate limits de la API
                time.sleep(0.05)

            except Exception as e:
                print(f"   [ERROR] Falló el registro ID {reg.get('id')}: {str(e)}")
                continue

        if len(registros) < BATCH_SIZE:
            break

    print(f"\n🎉 ¡Proceso de vectorización finalizado con éxito! Total procesados en esta sesión: {procesados}")

if __name__ == "__main__":
    poblar_embeddings()