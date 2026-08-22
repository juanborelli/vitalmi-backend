from supabase import create_client, Client
from app.core.config import settings

def get_supabase_client() -> Client:
    """
    Inicializa y retorna la conexión con Supabase
    usando las credenciales configuradas en el .env
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

# Instancia global lista para usar en el resto de la app
supabase: Client = get_supabase_client()