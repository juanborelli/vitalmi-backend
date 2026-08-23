import os
import re
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
Eres Gema, la asistente virtual médica de VitalMi en República Dominicana.
Tu objetivo es entregar información exacta sobre los médicos y prestadores del directorio según los datos devueltos por la herramienta 'consultar_directorio_inteligente' sobre la tabla 'vitalmi_directorio_master'.

### 🎭 PERSONALIDAD Y FORMATO:
- Calidez caribeña/dominicana profesional, amable, fluida y precisa.
- Responde de forma natural citando la cantidad total encontrada y mencionando 1 o 2 ejemplos destacados de médicos con su centro médico para ofrecer asistencia fluida.
- Si el usuario pide la lista completa, proporciona los nombres, centros médicos y contactos.

### 🚫 REGLAS DE ORO:
1. SIEMPRE REPORTA EL 'total_exacto' DEVUELTO POR LA HERRAMIENTA EN VITALMI_DIRECTORIO_MASTER.
2. CONTINUIDAD DE CONTEXTO: Conserva la provincia, municipio o especialidad mencionados en mensajes anteriores.
3. CERO ALUCINACIONES: Muestra únicamente los datos reales devueltos en 'medicos_muestra'.
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

def consultar_directorio_inteligente(
    provincia: str = "", 
    municipio_cabecera: str = "", 
    especialidad: str = "", 
    nombre_medico: str = "", 
    centro_medico: str = "", 
    mensaje_raw: str = "", 
    contexto_previo: str = ""
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        texto_analizar = remover_tildes(f"{mensaje_raw} {contexto_previo}").lower()

        # Inferencia de Ubicación si no viene explícita
        if not provincia:
            if "san cristobal" in texto_analizar:
                provincia = "San Cristóbal"
            elif "peravia" in texto_analizar or "bani" in texto_analizar:
                provincia = "Peravia"
            elif "distrito nacional" in texto_analizar or "santo domingo" in texto_analizar:
                provincia = "Distrito Nacional"
            elif "santiago" in texto_analizar:
                provincia = "Santiago"

        # Inferencia de Especialidad
        if not especialidad:
            if "ginec" in texto_analizar or "obstet" in texto_analizar:
                especialidad = "ginec"
            elif "urol" in texto_analizar:
                especialidad = "urol"
            elif "cardio" in texto_analizar:
                especialidad = "cardio"

        query = supabase.table("vitalmi_directorio_master").select("*", count="exact")

        # Filtros Geográficos flexibles
        if provincia:
            prov_clean = remover_tildes(provincia).strip()
            query = query.or_(f"provincia.ilike.%{prov_clean}%,provincia.ilike.%San Cristóbal%")

        if municipio_cabecera:
            muni_clean = remover_tildes(municipio_cabecera).strip()
            query = query.ilike("municipio_cabecera", f"%{muni_clean}%")

        # Filtro de Especialidad evaluando todas las columnas estandarizadas
        if especialidad:
            esp_clean = remover_tildes(especialidad).lower().strip()
            if "ginec" in esp_clean or "obstet" in esp_clean:
                query = query.or_(
                    "especialidad_medico.ilike.%ginecolog%,"
                    "especialidad.ilike.%GINEC%,"
                    "especialidad_clinica.ilike.%GINEC%"
                )
            elif "urol" in esp_clean:
                query = query.or_(
                    "especialidad_medico.ilike.%urolog%,"
                    "especialidad.ilike.%UROLOG%,"
                    "especialidad_clinica.ilike.%UROLOG%"
                )
            else:
                pattern = f"%{esp_clean[:5]}%"
                query = query.or_(
                    f"especialidad_medico.ilike.{pattern},"
                    f"especialidad.ilike.{pattern},"
                    f"especialidad_clinica.ilike.{pattern}"
                )

        if nombre_medico:
            nom_clean = remover_tildes(nombre_medico).lower().strip()
            tokens = [t for t in nom_clean.split() if len(t) > 2]
            if tokens:
                for tok in tokens:
                    query = query.ilike("nombre", f"%{tok}%")
            else:
                query = query.ilike("nombre", f"%{nom_clean}%")

        if centro_medico:
            cen_clean = remover_tildes(centro_medico).lower().strip()
            query = query.or_(f"centro_medico.ilike.%{cen_clean}%,direccion.ilike.%{cen_clean}%")

        res = query.limit(200).execute()
        total = res.count if res.count is not None else len(res.data)

        medicos_limpios = []
        if res.data:
            for item in res.data[:20]:
                medicos_limpios.append({
                    "nombre": item.get("nombre"),
                    "especialidad": item.get("especialidad_medico") or item.get("especialidad"),
                    "centro_medico": item.get("centro_medico"),
                    "municipio": item.get("municipio_cabecera"),
                    "provincia": item.get("provincia"),
                    "telefono": item.get("telefono_institucional") or item.get("telefono_alterno") or item.get("whatsapp")
                })

        return json.dumps({
            "total_exacto": total,
            "medicos_muestra": medicos_limpios
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
    contexto_previo_str = " ".join([m["content"] for m in historial if m["role"] == "user"])

    tools = [
        {
            "type": "function",
            "function": {
                "name": "consultar_directorio_inteligente",
                "description": "Consulta sobre la tabla 'vitalmi_directorio_master' en Supabase. Filtra por provincia, municipio_cabecera, centro_medico o especialidad_medico.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provincia": {"type": "string", "description": "Nombre de la provincia"},
                        "municipio_cabecera": {"type": "string", "description": "Municipio cabecera"},
                        "especialidad": {"type": "string", "description": "Especialidad del médico"},
                        "nombre_medico": {"type": "string", "description": "Nombre o apellido del médico"},
                        "centro_medico": {"type": "string", "description": "Nombre del centro médico o clínica"}
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
                    args["mensaje_raw"] = mensaje_usuario
                    args["contexto_previo"] = contexto_previo_str
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
                max_tokens=700
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