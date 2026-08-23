import os
import json
from datetime import datetime
import zoneinfo
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv
from openai import AsyncOpenAI
from app.core.supabase import obtener_cliente_supabase

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

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

SYSTEM_PROMPT_FASE_1 = """
Eres Gema, la asistente virtual de VitalMi en República Dominicana.
Tu función es responder preguntas sobre el directorio médico usando la información EXACTA obtenida de la base de datos mediante tus herramientas de consulta.

### 🎭 PERSONALIDAD Y TONO:
- Calidez caribeña/dominicana profesional, amable, directa y natural.
- Responde de forma fluida y conversacional en máximo 2-3 oraciones corridas.
- NO utilices listas numeradas, viñetas (*, -) ni formatos rígidos.

### 🚫 REGLAS DE ORO:
1. CERO PROMESAS DE BÚSQUEDA: JAMÁS digas "voy a buscar", "un momento por favor", "te daré los detalles" ni "voy a revisar".
2. PRECISIÓN ABSOLUTA: Confía al 100% en los números y datos devueltos por la herramienta 'consultar_directorio_inteligente'.
3. CERO ALUCINACIONES: NUNCA inventes médicos, clínicas ni números telefónicos.
"""

def obtener_hora_rd_iso() -> str:
    return datetime.now(TZ_RD).isoformat()

def remover_tildes(texto: str) -> str:
    if not texto:
        return ""
    replacements = (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
        ("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("ñ", "n"), ("Ñ", "N")
    )
    for a, b in replacements:
        texto = texto.replace(a, b)
    return texto.strip()

def consultar_directorio_inteligente(ciudad_provincia: str = "", especialidad: str = "", nombre_medico: str = "", centro_medico: str = "", horario_tarde: bool = False, solo_conteo: bool = False) -> str:
    """
    Peina el 100% de la tabla vitalmi_directorio_master en Supabase.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        # Petición con límite alto explícito (5000) para evitar que Supabase corte en 23 o 100
        res = supabase.table("vitalmi_directorio_master").select("*").limit(5000).execute()
        registros = res.data if res.data else []

        if not registros:
            return json.dumps({"total_exacto": 0, "medicos_muestra": []})

        prov_busqueda = remover_tildes(ciudad_provincia).lower().strip()
        esp_busqueda = remover_tildes(especialidad).lower().strip()
        nom_busqueda = remover_tildes(nombre_medico).lower().strip()
        centro_busqueda = remover_tildes(centro_medico).lower().strip()

        # Mapeo flexible de raíces clínicas
        raices_especialidad = []
        if "ginecolog" in esp_busqueda or "obstetr" in esp_busqueda:
            raices_especialidad = ["ginecolog", "obstetr", "ginecobstetr"]
        elif "cardiol" in esp_busqueda:
            raices_especialidad = ["cardiol"]
        elif "pediatr" in esp_busqueda:
            raices_especialidad = ["pediatr"]
        elif "otorrin" in esp_busqueda:
            raices_especialidad = ["otorrin"]
        elif esp_busqueda:
            raices_especialidad = [esp_busqueda]

        filtrados = []
        for m in registros:
            prov = remover_tildes(str(m.get("ciudad_provincia") or "")).lower()
            dir_text = remover_tildes(str(m.get("direccion") or "")).lower()
            sec_text = remover_tildes(str(m.get("sector") or "")).lower()
            
            esp_full = remover_tildes(
                str(m.get("especialidad_medico") or "") + " " +
                str(m.get("especialidad") or "") + " " +
                str(m.get("especialidad_clinica") or "") + " " +
                str(m.get("subespecialidades_medico") or "")
            ).lower()
            
            nom_med = remover_tildes(str(m.get("nombre") or "")).lower()
            cen_med = remover_tildes(str(m.get("centro_medico") or "")).lower()
            horarios = remover_tildes(str(m.get("horario_atencion") or m.get("observaciones") or "")).lower()

            # 1. Ubicación/Provincia
            match_loc = True
            if prov_busqueda:
                match_loc = (prov_busqueda in prov) or (prov_busqueda in dir_text) or (prov_busqueda in sec_text)

            # 2. Especialidad
            match_esp = True
            if raices_especialidad:
                match_esp = any(r in esp_full for r in raices_especialidad)

            # 3. Nombre
            match_nom = True
            if nom_busqueda:
                tokens_nombre = [t for t in nom_busqueda.split() if len(t) > 2]
                match_nom = any(tok in nom_med for tok in tokens_nombre) if tokens_nombre else (nom_busqueda in nom_med)

            # 4. Centro Médico / Clínica
            match_centro = True
            if centro_busqueda:
                match_centro = (centro_busqueda in cen_med) or (centro_busqueda in dir_text)

            # 5. Horario Tarde
            match_horario = True
            if horario_tarde:
                match_horario = any(p in horarios for p in ["tarde", "pm", "14:", "15:", "16:", "17:", "18:", "2:00", "3:00", "4:00", "5:00", "6:00"])

            if match_loc and match_esp and match_nom and match_centro and match_horario:
                filtrados.append({
                    "nombre": m.get("nombre"),
                    "especialidad": m.get("especialidad_medico") or m.get("especialidad"),
                    "centro_medico": m.get("centro_medico"),
                    "direccion": m.get("direccion"),
                    "ciudad_provincia": m.get("ciudad_provincia"),
                    "telefono": m.get("telefono_institucional") or m.get("whatsapp"),
                    "horarios": m.get("horario_atencion") or m.get("observaciones")
                })

        total = len(filtrados)
        return json.dumps({
            "total_exacto": total,
            "medicos_muestra": filtrados[:10] if not solo_conteo else []
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en consultar_directorio_inteligente: {e}")
        return json.dumps({"error": str(e)})

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

    tools = [
        {
            "type": "function",
            "function": {
                "name": "consultar_directorio_inteligente",
                "description": "Consulta y peina la totalidad de registros (hasta 5000) en vitalmi_directorio_master para responder conteos o búsquedas detalladas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ciudad_provincia": {"type": "string", "description": "Nombre de la ciudad o provincia (ej. 'San Cristóbal', 'Santiago')"},
                        "especialidad": {"type": "string", "description": "Especialidad médica (ej. 'Ginecología', 'Obstetricia', 'Cardiología')"},
                        "nombre_medico": {"type": "string", "description": "Nombre o apellido del médico"},
                        "centro_medico": {"type": "string", "description": "Nombre de la clínica o centro médico (ej. 'Cemeco', 'Constitución')"},
                        "horario_tarde": {"type": "boolean", "description": "True si el usuario pregunta si atienden por la tarde"},
                        "solo_conteo": {"type": "boolean", "description": "True si la pregunta es 'cuántos'"}
                    },
                    "required": []
                }
            }
        }
    ]

    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    system_prompt = SYSTEM_PROMPT_FASE_1 + contexto_usuario

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.0
        )

        response_message = response.choices[0].message

        if response_message.tool_calls:
            messages.append(response_message)
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "consultar_directorio_inteligente":
                    args = json.loads(tool_call.function.arguments)
                    resultado_json = consultar_directorio_inteligente(**args)
                    
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "consultar_directorio_inteligente",
                        "content": resultado_json
                    })

            second_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.0,
                max_tokens=350
            )
            respuesta_texto = second_response.choices[0].message.content.strip()
        else:
            respuesta_texto = response_message.content.strip()

        guardar_mensaje_supabase(numero_usuario, "assistant", respuesta_texto)
        return respuesta_texto

    except Exception as e:
        print(f"❌ Error en gema_brain: {e}")
        return "Tuve un pequeño inconveniente técnico. ¿Podrías repetirme tu mensaje, por favor?"

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)