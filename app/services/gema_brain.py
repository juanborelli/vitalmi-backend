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
Tu objetivo es entregar información exacta del directorio ('consultar_directorio_inteligente'), gestionar disponibilidades por TANDAS ('consultar_horario_y_bloqueos'), AGENDAR CITAS ('agendar_cita_medica') y PERMITIR CONSULTAR O CANCELAR CITAS REGISTRADAS ('consultar_mis_citas', 'gestionar_estado_cita').

### 🎭 PERSONALIDAD Y FORMATO:
- Calidez caribeña/dominicana profesional, amable, fluida y precisa.
- Si el usuario pregunta por sus citas agendadas, usa 'consultar_mis_citas' y muéstraselas claramente.
- Si el usuario desea cancelar una cita, usa 'gestionar_estado_cita' pasando el ID de la cita y confirmando amablemente la cancelación.

### 🚫 REGLAS DE ORO:
1. SIEMPRE REPORTA DATOS REALES DE VITALMI_DIRECTORIO_MASTER, DOCTORES_HORARIOS Y CITAS.
2. CONTINUIDAD DE CONTEXTO: Conserva los datos de citas y preferencias mencionadas previamente.
3. CERO ALUCINACIONES: Muestra únicamente confirmaciones e IDs reales devueltos por la base de datos.
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

def consultar_mis_citas(telefono_jid: str) -> str:
    """
    Recupera las citas activas del paciente vinculadas a su teléfono.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        res_pac = supabase.table("pacientes").select("id").eq("telefono_jid", telefono_jid).execute()
        if not res_pac.data:
            return json.dumps({"citas": [], "mensaje": "No se encontró registro de paciente."})

        paciente_id = res_pac.data[0].get("id")
        res_citas = supabase.table("citas") \
            .select("*") \
            .eq("paciente_id", paciente_id) \
            .neq("estado", "cancelada") \
            .order("created_at", desc=True) \
            .execute()

        return json.dumps({
            "total_citas": len(res_citas.data) if res_citas.data else 0,
            "citas": res_citas.data or []
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en consultar_mis_citas: {e}")
        return json.dumps({"error": str(e)})

def gestionar_estado_cita(cita_id: str, nuevo_estado: str = "cancelada") -> str:
    """
    Actualiza el estado de una cita en Supabase (ej. 'cancelada' o 'reprogramada').
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        res = supabase.table("citas").update({"estado": nuevo_estado}).eq("id", cita_id).execute()
        return json.dumps({
            "status": "exitoso",
            "mensaje": f"La cita ha sido actualizada a estado '{nuevo_estado}' correctamente en VitalMi.",
            "cita_id": cita_id
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en gestionar_estado_cita: {e}")
        return json.dumps({"error": str(e)})

def agendar_cita_medica(
    telefono_jid: str, 
    medico_nombre: str, 
    fecha_cita: str, 
    tanda: str, 
    motivo_consulta: str = "Consulta General"
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        res_pac = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        paciente_id = res_pac.data[0].get("id") if (res_pac.data and len(res_pac.data) > 0) else None

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Médico: {medico_nombre} | Tanda: {tanda} | Motivo: {motivo_consulta} | Fecha: {fecha_cita}",
            "estado": "solicitada",
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        return json.dumps({
            "status": "exitoso",
            "mensaje": "Cita registrada correctamente en el sistema de VitalMi.",
            "cita_id": cita_creada.get("id"),
            "detalles": {
                "medico": medico_nombre,
                "fecha": fecha_cita,
                "tanda": tanda,
                "estado": "solicitada"
            }
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en agendar_cita_medica: {e}")
        return json.dumps({"error": str(e)})

def consultar_horario_y_bloqueos(medico_master_id: int, fecha_consulta: str = "") -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        if not fecha_consulta:
            fecha_consulta = datetime.now(TZ_RD).strftime("%Y-%m-%d")

        fecha_dt = datetime.strptime(fecha_consulta, "%Y-%m-%d")
        dias_semana = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
        nombre_dia = dias_semana[fecha_dt.weekday()]

        if nombre_dia == "domingo":
            return json.dumps({"status": "no_disponible", "motivo": "Los domingos no se ofrece consulta regular."})

        res_doc = supabase.table("doctores_horarios").select("*").eq("medico_master_id", medico_master_id).execute()
        
        horario_base = {
            "lunes": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
            "martes": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
            "miercoles": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
            "jueves": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
            "viernes": [{"bloque": "mañana", "inicio": "09:00", "fin": "12:00"}, {"bloque": "tarde", "inicio": "15:00", "fin": "18:00"}],
            "sabado": [{"bloque": "mañana", "inicio": "09:00", "fin": "14:00"}]
        }
        doctor_horario_id = None

        if res_doc.data:
            doctor_data = res_doc.data[0]
            doctor_horario_id = doctor_data.get("id")
            if doctor_data.get("horario_base"):
                horario_base = doctor_data.get("horario_base")

        tandas_dia = horario_base.get(nombre_dia, [])

        bloqueos_existentes = []
        if doctor_horario_id:
            res_bloqueos = supabase.table("bloqueos_medicos") \
                .select("*") \
                .eq("doctor_horario_id", doctor_horario_id) \
                .lte("fecha_inicio", fecha_consulta) \
                .gte("fecha_fin", fecha_consulta) \
                .execute()
            bloqueos_existentes = res_bloqueos.data or []

        tandas_finales = []
        for t in tandas_dia:
            bloqueado = False
            for b in bloqueos_existentes:
                if b.get("bloque") == "todo_el_dia" or b.get("bloque") == t.get("bloque") or b.get("tipo_bloqueo") == "rango_fechas":
                    bloqueado = True
                    break
            if not bloqueado:
                tandas_finales.append(t)

        return json.dumps({
            "fecha": fecha_consulta,
            "dia": nombre_dia,
            "tandas_disponibles": tandas_finales,
            "bloqueos_activos": len(bloqueos_existentes) > 0
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en consultar_horario_y_bloqueos: {e}")
        return json.dumps({"error": str(e)})

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

        if not provincia:
            if "san cristobal" in texto_analizar:
                provincia = "San Cristóbal"
            elif "peravia" in texto_analizar or "bani" in texto_analizar:
                provincia = "Peravia"
            elif "distrito nacional" in texto_analizar or "santo domingo" in texto_analizar:
                provincia = "Distrito Nacional"
            elif "santiago" in texto_analizar:
                provincia = "Santiago"

        if not especialidad:
            if "ginec" in texto_analizar or "obstet" in texto_analizar:
                especialidad = "ginec"
            elif "urol" in texto_analizar:
                especialidad = "urol"
            elif "cardio" in texto_analizar:
                especialidad = "cardio"

        query = supabase.table("vitalmi_directorio_master").select("*", count="exact")

        if provincia:
            prov_clean = remover_tildes(provincia).strip()
            query = query.or_(f"provincia.ilike.%{prov_clean}%,provincia.ilike.%San Cristóbal%")

        if municipio_cabecera:
            muni_clean = remover_tildes(municipio_cabecera).strip()
            query = query.ilike("municipio_cabecera", f"%{muni_clean}%")

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
                    "id": item.get("id"),
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
                "description": "Consulta sobre la tabla 'vitalmi_directorio_master'. Filtra por provincia, municipio_cabecera, centro_medico o especialidad.",
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
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_horario_y_bloqueos",
                "description": "Obtiene las tandas de horarios disponibles (Mañana / Tarde) para un médico específico según su ID y fecha.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medico_master_id": {"type": "integer", "description": "ID del médico en vitalmi_directorio_master"},
                        "fecha_consulta": {"type": "string", "description": "Fecha en formato YYYY-MM-DD (ej. '2026-08-25')"}
                    },
                    "required": ["medico_master_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "agendar_cita_medica",
                "description": "Registra una cita médica formal para el usuario en la tabla 'citas' de Supabase.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medico_nombre": {"type": "string", "description": "Nombre completo del médico"},
                        "fecha_cita": {"type": "string", "description": "Fecha solicitada para la cita"},
                        "tanda": {"type": "string", "description": "Tanda elegida: 'Mañana' o 'Tarde'"},
                        "motivo_consulta": {"type": "string", "description": "Motivo de la consulta médica"}
                    },
                    "required": ["medico_nombre", "fecha_cita", "tanda"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_mis_citas",
                "description": "Muestra las citas activas registradas para el usuario actual.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "gestionar_estado_cita",
                "description": "Cancela o actualiza el estado de una cita médica.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cita_id": {"type": "string", "description": "UUID de la cita a gestionar"},
                        "nuevo_estado": {"type": "string", "description": "Nuevo estado (ej. 'cancelada')"}
                    },
                    "required": ["cita_id"]
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
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if name == "consultar_directorio_inteligente":
                    args["mensaje_raw"] = mensaje_usuario
                    args["contexto_previo"] = contexto_previo_str
                    res_tool = consultar_directorio_inteligente(**args)
                elif name == "consultar_horario_y_bloqueos":
                    res_tool = consultar_horario_y_bloqueos(**args)
                elif name == "agendar_cita_medica":
                    args["telefono_jid"] = numero_usuario
                    res_tool = agendar_cita_medica(**args)
                elif name == "consultar_mis_citas":
                    res_tool = consultar_mis_citas(telefono_jid=numero_usuario)
                elif name == "gestionar_estado_cita":
                    res_tool = gestionar_estado_cita(**args)
                else:
                    res_tool = json.dumps({"error": "Herramienta no encontrada"})

                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": name,
                    "content": res_tool
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