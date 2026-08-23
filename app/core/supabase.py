import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# Forzar la carga de .env desde la raíz del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

def obtener_cliente_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    # Acepta cualquier variante del nombre de la clave en el .env
    key = (
        os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )

    if not url or not key:
        print("⚠️ SUPABASE_URL o SUPABASE_KEY no configuradas en las variables de entorno.")
        return None

    try:
        return create_client(url, key)
    except Exception as e:
        print(f"❌ Error al conectar con Supabase: {e}")
        return None