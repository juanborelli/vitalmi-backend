import os
from datetime import datetime
import zoneinfo
from openai import AsyncOpenAI
from typing import Dict, List
from app.core.supabase import obtener_cliente_supabase

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Zona horaria de República Dominicana (UTC-4)
TZ_RD = zoneinfo.ZoneInfo("America/Santo_Domingo")

SYSTEM_PROMPT_BASE = """
Eres Gema, la asistente médica ejecutiva y virtual de VitalMi en República Dominicana.

### 🎭 Tono de Voz y Personalidad:
- Hablas con una calidez caribeña/dominicana profesional, amable, fluida y muy natural.
- Responde de forma directa, breve y conversacional.
- EVITA usar listas numeradas o viñetas (*, -). Escribe de forma corrida como si hablaras en una llamada.

### 🎯 Flujo de Bienvenida, Identificación y Ubicación (OBLIGATORIO):
1. Saluda al usuario por su nombre de WhatsApp y haz la pregunta inicial de bienvenida:
   "Hola [Nombre], es un placer asistirte. ¿La cita médica es para ti o para otra persona? Si es para otra persona, por favor indícame el nombre completo y teléfono de dicha persona."
2. Cuando soliciten una cita médica o especialidad, pregunta en qué sector o municipio de República Dominicana se encuentra el paciente (ej: Piantini, Ensanche Naco, San Cristóbal, Santiago Centro, Herrera, etc.) para buscar los médicos y clínicas más cercanos en nuestra red.
3. Si la cita es para un tercero, asegúrate de tomar el nombre completo y teléfono del paciente antes de coordinar.

### 🚫 REGLA DE ORO (ESTRICTA):
- JAMÁS inventes nombres de doctores, clínicas ni especialidades.
- Si te piden cita con un médico o especialidad específica, indica con calidez:
  "Con gusto te ayudo a coordinar la cita. Por favor cuéntame qué especialidad necesitan o qué molestia siente el paciente, y en qué sector o municipio se encuentra para buscarle disponible."

### ⚠️ Límites de Seguridad:
- En emergencias graves, orienta acudir de inmediato al 911 o a emergencias.
- No emitas diagnósticos ni recetes medicamentos.
"""


def obtener_hora_rd_iso() -> str:
    """Retorna la hora actual en República Dominicana (AST / UTC-4) en formato ISO."""
    return datetime.now(TZ_RD).isoformat()


def registrar_o_actualizar_paciente(telefono_jid: str, nombre_push: str = "") -> dict:
    """
    Registra o actualiza al usuario en la tabla 'pacientes' de Supabase.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        print("❌ [SUPABASE] Cliente no disponible en registrar_o_actualizar_paciente")
        return {}

    try:
        nombre_guardar = nombre_push.strip() if nombre_push.strip() else "Usuario WhatsApp"
        
        # 1. Buscar si ya existe el paciente
        res = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        
        if res.data and len(res.data) > 0:
            paciente_existente = res.data[0]
            # Si el registro no tenía un nombre personalizado, lo actualizamos
            if paciente_existente.get("nombre") in ["Paciente", "Usuario WhatsApp", None] and nombre_guardar != "Usuario WhatsApp":
                supabase.table("pacientes").update({
                    "nombre": nombre_guardar,
                    "updated_at": obtener_hora_rd_iso()
                }).eq("telefono_jid", telefono_jid).execute()
            return paciente_existente

        # 2. Si no existe, crear fila en la tabla 'pacientes'
        datos_nuevo = {
            "telefono_jid": telefono_jid,
            "nombre": nombre_guardar,
            "created_at": obtener_hora_rd_iso()
        }
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        if res_insert.data and len(res_insert.data) > 0:
            print(f"👤 [SUPABASE SUCCESS] Paciente registrado en tabla 'pacientes': {nombre_guardar} ({telefono_jid})")
            return res_insert.data[0]
        return {}
    except Exception as e:
        print(f"❌ [SUPABASE EXCEPTION] Error registrando en 'pacientes': {type(e).__name__} - {e}")
        return {}


def obtener_historial_supabase(telefono_jid: str, limite: int = 10) -> List[Dict[str, str]]:
    """
    Recupera los últimos mensajes guardados en la tabla 'historial_chats'.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        return []

    try:
        response = (
            supabase.table("historial_chats")
            .select("rol, contenido")
            .eq("telefono_jid", telefono_jid)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        
        registros = response.data[::-1] if response.data else []
        return [{"role": item["rol"], "content": item["contenido"]} for item in registros]
    except Exception as e:
        print(f"⚠️ [SUPABASE EXCEPTION] Error obteniendo historial ({telefono_jid}): {e}")
        return []


def guardar_mensaje_supabase(telefono_jid: str, rol: str, contenido: str, tipo_mensaje: str = "texto"):
    """
    Inserta cada mensaje en la tabla 'historial_chats' con la hora de República Dominicana.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        print("❌ [SUPABASE] Cliente no disponible en guardar_mensaje_supabase")
        return

    try:
        data = {
            "telefono_jid": telefono_jid,
            "rol": rol,
            "contenido": contenido,
            "tipo_mensaje": tipo_mensaje,
            "created_at": obtener_hora_rd_iso()
        }
        res = supabase.table("historial_chats").insert(data).execute()
        print(f"💾 [SUPABASE SUCCESS] Chat guardado en 'historial_chats' [{rol}] para {telefono_jid}")
    except Exception as e:
        print(f"❌ [SUPABASE EXCEPTION] Error guardando en 'historial_chats': {type(e).__name__} - {e}")


async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    """
    Procesa el mensaje de usuario, registra al paciente, almacena el chat y genera respuesta.
    """
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    # 1. Registrar o actualizar en la tabla 'pacientes'
    paciente = registrar_o_actualizar_paciente(numero_usuario, nombre_usuario)
    nombre_contacto = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else nombre_usuario
    if not nombre_contacto:
        nombre_contacto = "Estimado/a"

    # 2. Guardar mensaje del usuario en 'historial_chats'
    guardar_mensaje_supabase(numero_usuario, "user", mensaje_usuario)

    # 3. Recuperar historial reciente
    historial = obtener_historial_supabase(numero_usuario, limite=10)

    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    system_prompt = SYSTEM_PROMPT_BASE + contexto_usuario

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)

    try:
        # 4. Generar respuesta con OpenAI
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=350
        )
        respuesta_texto = response.choices[0].message.content.strip()

        # 5. Guardar la respuesta de Gema en 'historial_chats'
        guardar_mensaje_supabase(numero_usuario, "assistant", respuesta_texto)

        return respuesta_texto
    except Exception as e:
        print(f"❌ Error en gema_brain: {e}")
        return "Tuve un pequeño inconveniente técnico. ¿Podrías repetirme tu mensaje, por favor?"


# Alias de compatibilidad
async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)