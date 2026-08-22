import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Cargar variables del archivo .env automáticamente
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def obtener_cliente_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️ SUPABASE_URL o SUPABASE_KEY no configuradas en las variables de entorno.")
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"❌ Error al conectar con Supabase: {e}")
        return None