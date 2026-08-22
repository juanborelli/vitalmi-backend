import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Configuración general del proyecto
    PROJECT_NAME: str = "VitalMi API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # Supabase (Base de Datos) - Con valores por defecto de respaldo
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # Evolution API (WhatsApp) - Con valores por defecto de respaldo
    EVOLUTION_API_URL: str = os.getenv("EVOLUTION_API_URL", "https://example.com")
    EVOLUTION_API_KEY: str = os.getenv("EVOLUTION_API_KEY", "default_key")

    # Configuración de Pydantic V2 para cargar el archivo .env automáticamente
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignora variables de entorno adicionales no declaradas
    )


# Instancia global de configuración
settings = Settings()