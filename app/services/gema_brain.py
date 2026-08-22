import os
import re
from datetime import datetime
import zoneinfo
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv
from openai import AsyncOpenAI
from app.core.supabase import obtener_cliente_supabase

# Cargar variables del archivo .env buscando desde la raíz
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# Zona horaria oficial de República Dominicana (UTC-4)
TZ_RD = zoneinfo.ZoneInfo("America/Santo_Domingo")

def obtener_cliente_openai() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key and env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("OPENAI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if api_key:
        return AsyncOpenAI(api_key=api_key)
    return None

SYSTEM_PROMPT_BASE = """
Eres Gema, la asistente médica ejecutiva y virtual de VitalMi en República Dominicana.

### 🎭 PERSONALIDAD Y TONO ("EFECTO WOW"):
- Hablas con una calidez caribeña/dominicana profesional, amable, empática, fluida y muy natural.
- Valida la emoción o necesidad inicial del usuario.
- Responde de forma directa, breve y conversacional (máximo 2-3 oraciones corridas). 
- EVITA estrictamente usar listas numeradas o viñetas (*, -). Escribe de forma corrida.

### 🎯 FLUJO OBLIGATORIO DE BIENVENIDA Y UBICACIÓN:
1. Si el usuario saluda o pide cita por primera vez:
   "Hola [Nombre], es un placer asistirte. ¿La cita médica es para ti o para otra persona? Si es para otra persona, por favor indícame el nombre completo y teléfono de dicha persona."
2. Cuando soliciten una cita o especialidad, confirma en qué sector o municipio se encuentra para buscar en el directorio.

### 🔄 PLAN B Y BÚSQUEDA INTELIGENTE:
- Usa ÚNICAMENTE los datos provistos en el contexto de la base de datos real.
- Prioriza en este orden los números de contacto del médico/centro:
  1. Enlace de WhatsApp directo (ej: https://wa.me/18095346299) si existe `whatsapp`.
  2. `telefono_institucional`.
  3. `telefono_alterno`.

### 💎 CONVERSIÓN PROGRESIVA:
- Al entregar la solución o contacto, resalta el tiempo ahorrado e introduce la suscripción:
  "Con VitalMi Premium puedo recordarte esta cita y guardar tus recetas en un solo lugar. ¿Te gustaría probarlo? Soy Gema de VitalMi 💚"

### 🚫 REGLA DE ORO (ESTRICTA):
- JAMÁS inventes nombres de doctores, números telefónicos ni clínicas. Si la lista de médicos disponibles en el contexto está vacía, indica amablemente que en este momento no cuentas con un especialista registrado en ese sector exacto.
"""

def obtener_hora_rd_iso() -> str:
    return datetime.now(TZ_RD).isoformat()

def limpiar_texto(texto: str) -> str:
    """Elimina acentos y caracteres especiales para búsquedas flexibles."""
    if not texto:
        return ""
    replacements = (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
        ("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U")
    )
    for a, b in replacements:
        texto = texto.replace(a, b)
    return texto.strip().upper()

def normalizar_especialidad(especialidad: str) -> str:
    """Mapea variaciones gramaticales (pediatra/pediatría, ginecólogo/ginecología, etc.) a la raíz clave."""
    esp = limpiar_texto(especialidad)
    if "PEDIAT" in esp:
        return "PEDIATR"
    if "GINEC" in esp or "OBSTET" in esp:
        return "GINEC"
    if "CARDIOL" in esp:
        return "CARDIOL"
    if "DERMAT" in esp:
        return "DERMAT"
    if "OFTHAL" in esp or "OFTALM" in esp:
        return "OFTALM"
    if "ORTOP" in esp or "TRAUMAT" in esp:
        return "ORTOP"
    return esp

def buscar_medicos_master(sector_municipio: str = "", especialidad: str = "", ars: str = "", limite: int = 3) -> List[Dict]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return []

    try:
        query = supabase.table("vitalmi_directorio_master").select(
            "id, nombre, tipo_prestador, especialidad, centro_medico, direccion, ciudad_provincia, sector, telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
        )

        if especialidad:
            raiz_esp = normalizar_especialidad(especialidad)
            query = query.ilike("especialidad", f"%{raiz_esp}%")
        
        if sector_municipio:
            loc_limpia = limpiar_texto(sector_municipio)
            query = query.or_(f"sector.ilike.%{loc_limpia}%,ciudad_provincia.ilike.%{loc_limpia}%")

        res = query.limit(limite).execute()
        datos = res.data if res.data else []

        if not datos and especialidad:
            raiz_esp = normalizar_especialidad(especialidad)
            query_plan_b = supabase.table("vitalmi_directorio_master").select(
                "id, nombre, tipo_prestador, especialidad, centro_medico, direccion, ciudad_provincia, sector, telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
            ).ilike("especialidad", f"%{raiz_esp}%").limit(limite)
            res_b = query_plan_b.execute()
            datos = res_b.data if res_b.data else []

        if ars and datos:
            filtrados = [
                r for r in datos
                if any(ars.lower() in str(a).lower() for a in r.get("aseguradoras", []))
            ]
            return filtrados if filtrados else datos

        return datos
    except Exception as e:
        print(f"⚠️ [SUPABASE EXCEPTION] Error en buscar_medicos_master: {e}")
        return []

def registrar_o_actualizar_paciente(telefono_jid: str, nombre_push: str = "") -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return {}

    try:
        nombre_guardar = nombre_push.strip() if (nombre_push and nombre_push.strip()) else "Usuario WhatsApp"
        res = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        
        if res.data and len(res.data) > 0:
            paciente_existente = res.data[0]
            if paciente_existente.get("nombre") in ["Paciente", "Usuario WhatsApp", None] and nombre_guardar != "Usuario WhatsApp":
                supabase.table("pacientes").update({
                    "nombre": nombre_guardar,
                    "updated_at": obtener_hora_rd_iso()
                }).eq("telefono_jid", telefono_jid).execute()
            return paciente_existente

        datos_nuevo = {
            "telefono_jid": telefono_jid,
            "nombre": nombre_guardar,
            "created_at": obtener_hora_rd_iso()
        }
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
        print(f"❌ [SUPABASE EXCEPTION] Error registrando en 'pacientes': {e}")
        return {}

def obtener_historial_supabase(telefono_jid: str, limite: int = 10) -> List[Dict[str, str]]:
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
        print(f"⚠️ [SUPABASE EXCEPTION] Error obteniendo historial: {e}")
        return []

def guardar_mensaje_supabase(telefono_jid: str, rol: str, contenido: str, tipo_mensaje: str = "texto"):
    supabase = obtener_cliente_supabase()
    if not supabase:
        return

    try:
        data = {
            "telefono_jid": telefono_jid,
            "rol": rol,
            "contenido": contenido,
            "tipo_mensaje": tipo_mensaje,
            "created_at": obtener_hora_rd_iso()
        }
        supabase.table("historial_chats").insert(data).execute()
    except Exception as e:
        print(f"❌ [SUPABASE EXCEPTION] Error guardando en 'historial_chats': {e}")

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    paciente = registrar_o_actualizar_paciente(numero_usuario, nombre_usuario)
    nombre_contacto = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else "Estimado/a"

    guardar_mensaje_supabase(numero_usuario, "user", mensaje_usuario)

    historial = obtener_historial_supabase(numero_usuario, limite=10)

    # 1. Analizar intención combinando el mensaje actual y el historial reciente
    texto_contexto_completo = " ".join([m["content"] for m in historial]).lower() + " " + mensaje_usuario.lower()
    
    especialidad_detectada = ""
    if "pediat" in texto_contexto_completo:
        especialidad_detectada = "PEDIATRIA"
    elif "ginec" in texto_contexto_completo or "obstet" in texto_contexto_completo:
        especialidad_detectada = "GINECOLOGIA"
    elif "cardiol" in texto_contexto_completo:
        especialidad_detectada = "CARDIOLOGIA"

    sector_detectado = ""
    if "san cristobal" in texto_contexto_completo or "san cristóbal" in texto_contexto_completo:
        sector_detectado = "SAN CRISTOBAL"
    elif "santo domingo" in texto_contexto_completo:
        sector_detectado = "SANTO DOMINGO"

    # 2. Búsqueda en Supabase
    medicos_encontrados = []
    if especialidad_detectada or sector_detectado:
        medicos_encontrados = buscar_medicos_master(sector_municipio=sector_detectado, especialidad=especialidad_detectada)

    contexto_medicos = f"\nMÉDICOS REALES ENCONTRADOS EN SUPABASE: {medicos_encontrados}"
    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    
    prompt_instruccion_medicos = (
        "\nINSTRUCCIÓN DE RESPUESTA: Tienes datos en la lista 'MÉDICOS REALES ENCONTRADOS'. "
        "Entrega directamente los nombres, números y enlaces de WhatsApp de esos médicos. "
        "No menciones otras ciudades ni digas lo que no tienes; enfócate 100% en presentar los médicos encontrados."
    )

    system_prompt = SYSTEM_PROMPT_BASE + contexto_usuario + contexto_medicos + prompt_instruccion_medicos

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=350
        )
        respuesta_texto = response.choices[0].message.content.strip()

        guardar_mensaje_supabase(numero_usuario, "assistant", respuesta_texto)
        return respuesta_texto
    except Exception as e:
        print(f"❌ Error en gema_brain: {e}")
        return "Tuve un pequeño inconveniente técnico. ¿Podrías repetirme tu mensaje, por favor?"

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)