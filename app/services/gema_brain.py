import os
import re
import json
import logging
from datetime import datetime
import zoneinfo
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Importar las nuevas herramientas modulares
from app.services.directory_tools import buscar_directorio_salud, buscar_hospitales_emergencia
from app.core.supabase import obtener_cliente_supabase

# (Mantén aquí tus funciones de utilidad habituales: normalizar_jid, obtener_o_registrar_paciente, obtener_historial, agendar_cita_medica)
# ... [Para mantener la respuesta concisa, asume que tus funciones de utilería actuales van aquí] ...

# Configuración
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("GemaBrain")
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)
TZ_RD = zoneinfo.ZoneInfo("America/Santo_Domingo")

def obtener_cliente_openai() -> Optional[AsyncOpenAI]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if api_key: return AsyncOpenAI(api_key=api_key)
    return None

# ==========================================
# SYSTEM PROMPT (LOS 3 PILARES DE LÓGICA)
# ==========================================

SYSTEM_PROMPT_GEMA = """
Eres Gema, la asistente inteligente y empática de salud de VitalMi. 

Tu comportamiento se rige por TRES protocolos estrictos:

1. PROTOCOLO DE CRISIS (Emergencias):
   - Si el usuario menciona "emergencia", "herida", "infarto", "accidente", "sangrado" o peligro de muerte.
   - ACCIÓN INMEDIATA: Recomienda enfáticamente llamar al 911 o al número de emergencias local. 
   - SECUNDARIO: Ejecuta la herramienta `buscar_hospitales_emergencia` para darle el hospital más cercano, pero haz énfasis en el 911.

2. PROTOCOLO DE DESCUBRIMIENTO (Búsquedas):
   - Si el usuario busca médicos, farmacias, centros o especialidades.
   - DEBES ejecutar la herramienta `buscar_directorio_salud`.
   - NUNCA inventes médicos ni direcciones. Si la herramienta no devuelve resultados en la ciudad solicitada, discúlpate e invita al usuario a buscar en una ciudad vecina.

3. PROTOCOLO DE ACCIÓN (Agendar Citas):
   - Solo se activa cuando el usuario expresa su deseo claro de agendar con un médico o centro.
   - Ejecuta la herramienta `agendar_cita_medica`.

IMPORTANTE: 
- Extrae siempre la ubicación. Si el usuario no la menciona, asume su ciudad registrada en tu contexto.
- Sé directa, clara y empática. 
"""

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    
    # 1. Preparar Contexto
    jid_normalizado = normalizar_jid(numero_usuario) # Asegura tener definida esta funcion
    
    # Simulación de contexto de usuario (reemplaza con tu función obtener_o_registrar_paciente_por_whatsapp)
    ubicacion_str = "San Cristóbal, República Dominicana" 
    nombre_contacto = nombre_usuario or "Usuario"

    # 2. Historial Limpio (Mantén tu función obtener_historial_supabase)
    historial_limpio = [] # Aquí cargarías los últimos 6 mensajes
    
    contexto = f"\n\n🕒 Fecha actual: {datetime.now(TZ_RD).strftime('%Y-%m-%d %H:%M')}\n👤 Usuario: {nombre_contacto} | Ubicación Habitual: {ubicacion_str}"
    
    # 3. Definición de Herramientas para OpenAI
    tools = [
        {
            "type": "function",
            "function": {
                "name": "buscar_directorio_salud",
                "description": "Busca profesionales o entidades médicas en el directorio.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "ubicacion": {"type": "string", "description": "Provincia o sector. Usa la Ubicación Habitual si no se menciona otra."},
                        "tipo_busqueda": {"type": "string", "enum": ["medico", "centro", "farmacia", "nombre_especifico"]},
                        "termino": {"type": "string", "description": "Especialidad (ej: cardiologo), nombre del médico o centro."}
                    }, 
                    "required": ["ubicacion", "tipo_busqueda"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "buscar_hospitales_emergencia",
                "description": "Busca hospitales y clínicas de emergencia de manera rápida.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "ubicacion": {"type": "string", "description": "Ubicación de la emergencia."}
                    }, 
                    "required": ["ubicacion"]
                }
            }
        }
        # Nota: Aquí puedes volver a pegar tu definición de herramienta 'agendar_cita_medica'
    ]

    messages = [{"role": "system", "content": SYSTEM_PROMPT_GEMA + contexto}]
    messages.extend(historial_limpio)
    messages.append({"role": "user", "content": mensaje_usuario})

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.1
        )

        response_message = response.choices[0].message

        # Ejecución dinámica de herramientas
        if response_message.tool_calls:
            messages.append(response_message)

            for tool_call in response_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if name == "buscar_directorio_salud":
                    res_tool = buscar_directorio_salud(**args)
                elif name == "buscar_hospitales_emergencia":
                    res_tool = buscar_hospitales_emergencia(**args)
                # elif name == "agendar_cita_medica":
                #     res_tool = agendar_cita_medica(telefono_jid=jid_normalizado, **args)
                else:
                    res_tool = json.dumps({"error": "Herramienta desconocida"})

                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": name,
                    "content": res_tool
                })

            second_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.2
            )
            respuesta_texto = second_response.choices[0].message.content.strip()
        else:
            respuesta_texto = response_message.content.strip()

        # guardar_mensaje_supabase(jid_normalizado, "assistant", respuesta_texto)
        return respuesta_texto

    except Exception as e:
        logger.error(f"❌ Error en GemaBrain: {e}")
        return "Tuve un inconveniente técnico. ¿Me repites tu solicitud?"