import os
from typing import Dict, List
from app.services.gema_brain import obtener_respuesta_gema, procesar_mensaje_gema

async def obtener_respuesta_gema_service(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    """
    Wrapper de servicio que delega el procesamiento del mensaje a la inteligencia central de Gema.
    """
    return await obtener_respuesta_gema(
        mensaje_usuario=mensaje_usuario,
        numero_usuario=numero_usuario,
        nombre_usuario=nombre_usuario
    )

# Alias de compatibilidad para evitar roturas de importación en el proyecto
procesar_mensaje_gema = obtener_respuesta_gema_service