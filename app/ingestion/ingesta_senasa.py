import os
import json
import uuid
import time
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI

# Cargar variables de entorno desde el archivo .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# 1. Credenciales leídas de variables de entorno de forma segura
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://vpkbflsgfalydnfppgwz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_4viWrDy4LWSH8bskjDUevA__MjMPyiD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

# 2. Funciones Auxiliares
def generate_deterministic_uuid(codigo, proveedor):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{proveedor}-{codigo}"))

def get_embedding(text):
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

# 3. Función Principal de Ingesta Masiva (con reanudación y blindaje)
def process_and_upload():
    file_path = 'medicos_senasa.json'
    medicos = []

    print(f"Leyendo el archivo '{file_path}'...")
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read().strip()
            try:
                raw_data = json.loads(content)
                medicos = raw_data.get('result', {}).get('data', [])
            except json.JSONDecodeError:
                for line in content.splitlines():
                    if line.strip():
                        obj = json.loads(line)
                        data_chunk = obj.get('result', {}).get('data', [])
                        if isinstance(data_chunk, list):
                            medicos.extend(data_chunk)
                        else:
                            medicos.append(obj)
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo '{file_path}' en la raíz del proyecto.")
        return

    total_registros = len(medicos)
    
    # PUNTO DE REANUDACIÓN: Ajustado automáticamente al punto donde se detuvo
    inicio_desde = 4389 
    
    print(f"Total de registros en el JSON: {total_registros}")
    print(f"Reanudando la ingesta a partir del registro {inicio_desde}...\n")

    batch = []
    batch_size = 30  # Lotes más seguros para evitar saturaciones de red o timeouts

    for i, medico in enumerate(medicos[inicio_desde:], start=inicio_desde):
        try:
            telefonos = [t.strip() for t in str(medico.get('telefono', '')).split('|') if t.strip()]
            tel_inst = telefonos[0] if len(telefonos) > 0 else None
            tel_alt = telefonos[1] if len(telefonos) > 1 else None
            
            nombre = str(medico.get('nombre', '')).strip()
            especialidad = str(medico.get('especialidad', '')).strip()
            municipio = str(medico.get('municipio', '')).strip()
            direccion = str(medico.get('direccion', '')).strip()
            correo = str(medico.get('correo', '')).strip()

            texto_busqueda = f"{nombre}. Especialidad: {especialidad}. Ubicación: {direccion}, {municipio}."
            
            record = {
                "id": generate_deterministic_uuid(medico.get('codigoPrestador'), 'senasa'),
                "codigo_prestador_senasa": str(medico.get('codigoPrestador')),
                "nombre": nombre,
                "especialidad_medico": especialidad,
                "direccion": direccion,
                "municipio_cabecera": municipio,
                "email": correo if correo else None,
                "telefono_institucional": tel_inst,
                "telefono_alterno": tel_alt,
                "tipo_prestador": str(medico.get('tipoPrestador', '')).strip(),
                "aseguradoras": ["SeNaSa"],
                "embedding": get_embedding(texto_busqueda)
            }
            
            batch.append(record)

        except Exception as err:
            print(f"Advertencia: Omitiendo registro en el índice {i} por error en procesamiento: {err}")
            continue

        # Inserción en lotes y respiro para la API
        if len(batch) >= batch_size or i == total_registros - 1:
            if batch:
                try:
                    response = supabase.table('vitalmi_directorio_master').upsert(batch).execute()
                    print(f"Progreso: {i + 1} de {total_registros} registros procesados e insertados.")
                except Exception as e:
                    print(f"Error al insertar el lote en el índice {i}: {e}")
                batch = []
                time.sleep(0.3)  # Pausa breve para estabilidad de red

    print("\n¡Proceso de ingesta de SeNaSa finalizado con éxito!")

if __name__ == "__main__":
    process_and_upload()