import os
import re
import json
from datetime import datetime, timedelta
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
- Cuando pregunten por el horario de un médico, invoca 'consultar_horario_y_bloqueos' e informa siempre las tandas estándar (Tanda de la Mañana a partir de las 9:00 AM / Tanda de la Tarde a partir de las 3:00 PM).
- Si el usuario desea agendar, confirma la fecha utilizando el calendario exacto inyectado y especifica la tanda correspondiente.

### 🚫 REGLAS DE ORO:
1. NUNCA ASIGNES HORAS FIJAS FUERA DE TANDA (como "10:00 AM" o "4:00 PM"). Confirma siempre por TANDA ("Tanda de la Mañana a partir de las 9:00 AM" o "Tanda de la Tarde a partir de las 3:00 PM").
2. NUNCA DIGAS "Voy a verificar", "Un momento por favor" ni "Parece que hubo un problema".
3. USA ESTRICTAMENTE EL CALENDARIO INYECTADO PARA SABER LA FECHA EXACTA DE CADA DÍA DE LA SEMANA.
4. SIEMPRE REPORTA DATOS REALES DE VITALMI_DIRECTORIO_MASTER, DOCTORES_HORARIOS Y CITAS.
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

def resolver_fecha_relativa(texto_fecha: str) -> str:
    """
    Convierte referencias como 'martes', 'este viernes' o '25 de agosto'
    a formato YYYY-MM-DD usando la fecha real actual de RD.
    """
    ahora_rd = datetime.now(TZ_RD)
    texto_clean = remover_tildes(texto_fecha).lower().strip()

    dias_semana_map = {
        "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
        "viernes": 4, "sabado": 5, "domingo": 6
    }

    if re.match(r"^\d{4}-\d{2}-\d{2}$", texto_clean):
        return texto_clean

    for nombre_dia, idx_target in dias_semana_map.items():
        if nombre_dia in texto_clean:
            dias_diferencia = (idx_target - ahora_rd.weekday()) % 7
            if dias_diferencia == 0 and ("proximo" in texto_clean or "que viene" in texto_clean):
                dias_diferencia = 7
            fecha_calculada = ahora_rd + timedelta(days=dias_diferencia)
            return fecha_calculada.strftime("%Y-%m-%d")

    return ahora_rd.strftime("%Y-%m-%d")

def consultar_mis_citas(telefono_jid: str) -> str:
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
        # Resolucion matemática estricta de fecha con Python
        fecha_real_iso = resolver_fecha_relativa(fecha_cita)
        
        fecha_dt = datetime.strptime(fecha_real_iso, "%Y-%m-%d")
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        meses_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        
        nombre_dia = dias_es[fecha_dt.weekday()]
        nombre_mes = meses_es[fecha_dt.month - 1]
        fecha_formateada = f"{nombre_dia} {fecha_dt.day} de {nombre_mes} de {fecha_dt.year}"

        res_pac = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        paciente_id = res_pac.data[0].get("id") if (res_pac.data and len(res_pac.data) > 0) else None

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Médico: {medico_nombre} | Tanda: {tanda} | Motivo: {motivo_consulta} | Fecha: {fecha_formateada} ({fecha_real_iso})",
            "estado": "solicitada",
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        return json.dumps({
            "status": "exitoso",
            "mensaje": f"Cita registrada exitosamente para el {fecha_formateada}.",
            "cita_id": cita_creada.get("id"),
            "detalles": {
                "medico": medico_nombre,
                "fecha_confirmada": fecha_formateada,
                "fecha_iso": fecha_real_iso,
                "tanda": tanda,
                "estado": "solicitada"
            }
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en agendar_cita_medica: {e}")
        return json.dumps({"error": str(e)})

def consultar_horario_y_bloqueos(medico_master_id: int = 0, medico_nombre: str = "", fecha_consulta: str = "") -> str:
    supabase = obtener_cliente_supabase()
    
    horario_estandar = {
        "lunes_a_viernes": [
            {"bloque": "mañana", "inicio": "09:00 AM", "fin": "12:00 PM"},
            {"bloque": "tarde", "inicio": "03:00 PM", "fin": "06:00 PM"}
        ],
        "sabados": [
            {"bloque": "mañana", "inicio": "09:00 AM", "fin": "02:00 PM"}
        ],
        "domingos": "No se ofrece consulta regular."
    }

    try:
        if not fecha_consulta:
            fecha_consulta = datetime.now(TZ_RD).strftime("%Y-%m-%d")

        doctor_horario_id = None
        if supabase and medico_master_id > 0:
            res_doc = supabase.table("doctores_horarios").select("*").eq("medico_master_id", medico_master_id).execute()
            if res_doc.data:
                doctor_horario_id = res_doc.data[0].get("id")

        bloqueos_existentes = []
        if supabase and doctor_horario_id:
            res_bloqueos = supabase.table("bloqueos_medicos") \
                .select("*") \
                .eq("doctor_horario_id", doctor_horario_id) \
                .lte("fecha_inicio", fecha_consulta) \
                .gte("fecha_fin", fecha_consulta) \
                .execute()
            bloqueos_existentes = res_bloqueos.data or []

        return json.dumps({
            "status": "disponible",
            "horario_general": horario_estandar,
            "bloqueos_activos": len(bloqueos_existentes) > 0,
            "mensaje": "Horarios obtenidos correctamente."
        }, ensure_ascii=False)

    except Exception as e:
        print(f"⚠️ Fallback en consultar_horario_y_bloqueos: {e}")
        return json.dumps({"status": "disponible", "horario_general": horario_estandar}, ensure_ascii=False)

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

    # Generación de calendario exacto de los próximos 7 días
    ahora_rd = datetime.now(TZ_RD)
    dias_semana_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    
    proximos_dias = []
    for i in range(7):
        dia_futuro = ahora_rd + timedelta(days=i)
        nombre_d = dias_semana_es[dia_futuro.weekday()]
        fecha_f = dia_futuro.strftime("%d de %B de %Y")
        proximos_dias.append(f"- {nombre_d}: {fecha_f}")
    
    tabla_dias_str = "\n".join(proximos_dias)

    contexto_temporal = (
        f"\n\n### ⏰ ANCLA TEMPORAL Y CALENDARIO EXACTO DE HOY:\n"
        f"Hoy es {dias_semana_es[ahora_rd.weekday()]}, {ahora_rd.strftime('%d de %B de %Y')}.\n"
        f"Usa ESTA TABLA DE FECHA REAL para saber exactamente qué fecha le corresponde a cada día cuando el usuario te diga 'este lunes', 'el martes', etc.:\n"
        f"{tabla_dias_str}\n\n"
        f"REGLA DE ORO DE HORARIOS: Las consultas se gestionan exclusivamente por TANDAS (Tanda de la Mañana: 9:00 AM / Tanda de la Tarde: 3:00 PM). NUNCA asignes horas exactas inventadas como 10:00 AM o 4:00 PM."
    )
    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    
    system_prompt = SYSTEM_PROMPT_FASE_1 + contexto_temporal + contexto_usuario

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
                "description": "Obtiene las tandas de horarios disponibles (Mañana / Tarde) para un médico específico.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medico_master_id": {"type": "integer", "description": "ID del médico en vitalmi_directorio_master"},
                        "medico_nombre": {"type": "string", "description": "Nombre completo del médico"},
                        "fecha_consulta": {"type": "string", "description": "Fecha en formato YYYY-MM-DD"}
                    },
                    "required": []
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
                        "fecha_cita": {"type": "string", "description": "Texto del día solicitado (ej. 'martes', 'este viernes', '2026-08-25')"},
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