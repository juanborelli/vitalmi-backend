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

def obtener_hora_rd_iso() -> str:
    return datetime.now(TZ_RD).strftime("%Y-%m-%d %H:%M:%S")

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
            if dias_diferencia == 0 or "proximo" in texto_clean or "que viene" in texto_clean:
                if "proximo" in texto_clean or "que viene" in texto_clean or (dias_diferencia == 0 and ahora_rd.hour >= 12):
                    dias_diferencia += 7
                elif dias_diferencia == 0:
                    dias_diferencia = 7
            fecha_calculada = ahora_rd + timedelta(days=dias_diferencia)
            return fecha_calculada.strftime("%Y-%m-%d")

    return ahora_rd.strftime("%Y-%m-%d")

def registrar_o_actualizar_paciente(telefono_jid: str, nombre_push: str = "") -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return {}

    try:
        nombre_guardar = nombre_push.strip() if (nombre_push and nombre_push.strip()) else "Usuario WhatsApp"
        res = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        if res.data and len(res.data) > 0:
            paciente_existente = res.data[0]
            if paciente_existente.get("nombre") in ["Paciente", "Usuario WhatsApp", None, "Trancrédito"] and nombre_guardar not in ["Usuario WhatsApp", "Trancrédito"]:
                supabase.table("pacientes").update({
                    "nombre": nombre_guardar,
                    "updated_at": obtener_hora_rd_iso()
                }).eq("telefono_jid", telefono_jid).execute()
                paciente_existente["nombre"] = nombre_guardar
            return paciente_existente

        datos_nuevo = {
            "telefono_jid": telefono_jid, 
            "nombre": nombre_guardar, 
            "perfil_completo": False,
            "created_at": obtener_hora_rd_iso()
        }
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
        print(f"❌ Error registrando paciente: {e}")
        return {}

def obtener_historial_supabase(telefono_jid: str, limite: int = 6) -> List[Dict[str, str]]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return []

    try:
        response = (
            supabase.table("historial_chats")
            .select("rol, contenido, created_at")
            .eq("telefono_jid", telefono_jid)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        registros = response.data[::-1] if response.data else []
        return registros
    except Exception as e:
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
        print(f"❌ Error guardando mensaje: {e}")

def consultar_mis_citas(telefono_jid: str) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        res_pac = supabase.table("pacientes").select("id, nombre, cedula, ars").eq("telefono_jid", telefono_jid).execute()
        if not res_pac.data:
            return json.dumps({"citas": [], "mensaje": "No se encontró registro de paciente."})

        paciente_data = res_pac.data[0]
        paciente_id = paciente_data.get("id")
        
        res_citas = supabase.table("citas") \
            .select("*") \
            .eq("paciente_id", paciente_id) \
            .neq("estado", "cancelada") \
            .order("created_at", desc=True) \
            .execute()

        return json.dumps({
            "paciente": paciente_data,
            "total_citas": len(res_citas.data) if res_citas.data else 0,
            "citas": res_citas.data or []
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)})

def gestionar_estado_cita(cita_id: str = "", telefono_jid: str = "", nuevo_estado: str = "cancelada") -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        if cita_id:
            supabase.table("citas").update({"estado": nuevo_estado}).eq("id", cita_id).execute()
        elif telefono_jid:
            res_pac = supabase.table("pacientes").select("id").eq("telefono_jid", telefono_jid).execute()
            if res_pac.data:
                pac_id = res_pac.data[0].get("id")
                res_last = supabase.table("citas").select("id").eq("paciente_id", pac_id).neq("estado", "cancelada").order("created_at", desc=True).limit(1).execute()
                if res_last.data:
                    c_id = res_last.data[0].get("id")
                    supabase.table("citas").update({"estado": nuevo_estado}).eq("id", c_id).execute()

        return json.dumps({
            "status": "exitoso",
            "mensaje": f"La cita ha sido actualizada a estado '{nuevo_estado}' correctamente."
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)})

def agendar_cita_medica(
    telefono_jid: str, 
    medico_nombre: str, 
    fecha_cita: str, 
    tanda: str, 
    es_para_tercero: bool = False,
    nombre_paciente_tercero: str = "",
    telefono_paciente_tercero: str = "",
    cedula_paciente: str = "",
    ars_paciente: str = "",
    numero_afiliado_ars: str = "No especificado",
    tipo_plan_ars: str = "Básico/Estándar",
    motivo_consulta: str = "Consulta General / Primera Visita"
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        nombre_medico_limpio = medico_nombre.strip() if medico_nombre else "Médico General"
        fecha_real_iso = resolver_fecha_relativa(fecha_cita)
        
        fecha_dt = datetime.strptime(fecha_real_iso, "%Y-%m-%d")
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        meses_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        
        nombre_dia = dias_es[fecha_dt.weekday()]
        nombre_mes = meses_es[fecha_dt.month - 1]
        fecha_formateada = f"{nombre_dia} {fecha_dt.day} de {nombre_mes} de {fecha_dt.year}"

        res_pac = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        solicitante = res_pac.data[0] if (res_pac.data and len(res_pac.data) > 0) else {}
        paciente_id = solicitante.get("id")

        if es_para_tercero and nombre_paciente_tercero.strip():
            paciente_nombre_final = nombre_paciente_tercero.strip()
            paciente_whatsapp_final = telefono_paciente_tercero.strip() if telefono_paciente_tercero.strip() else telefono_jid.split("@")[0]
        else:
            paciente_nombre_final = solicitante.get("nombre") if solicitante.get("nombre") not in ["Trancrédito", "Usuario WhatsApp", "Paciente", None] else "Paciente Titular"
            paciente_whatsapp_final = telefono_jid.split("@")[0]

        paciente_cedula_final = cedula_paciente.strip() if cedula_paciente.strip() else (solicitante.get("cedula") or "No registrada")
        paciente_ars_final = ars_paciente.strip() if ars_paciente.strip() else (solicitante.get("ars") or "Privado")

        centro_medico = "Centro Médico Autorizado"
        telefono_doctor = "No disponible"
        
        tokens_medico = [t for t in remover_tildes(nombre_medico_limpio).split() if len(t) > 2]
        query_doc = supabase.table("vitalmi_directorio_master").select("centro_medico, whatsapp, telefono_institucional")
        for tok in tokens_medico[:2]:
            query_doc = query_doc.ilike("nombre", f"%{tok}%")
        
        res_doc = query_doc.limit(1).execute()
        if res_doc.data:
            centro_medico = res_doc.data[0].get("centro_medico") or centro_medico
            telefono_doctor = res_doc.data[0].get("whatsapp") or res_doc.data[0].get("telefono_institucional") or "No disponible"

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Paciente: {paciente_nombre_final} | Tel: {paciente_whatsapp_final} | Cédula: {paciente_cedula_final} | ARS: {paciente_ars_final} (No. Afiliado: {numero_afiliado_ars}, Plan: {tipo_plan_ars}) | Médico: {nombre_medico_limpio} | Centro: {centro_medico} | Tanda: {tanda} | Fecha: {fecha_formateada} | Motivo: {motivo_consulta}",
            "estado": "pendiente_aprobacion",
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        mensaje_final = (
            "📋 *SOLICITUD DE CITA REGISTRADA (SECTOR PRIVADO)*\n\n"
            "👤 *DATOS DEL PACIENTE:*\n"
            f"• *Nombre Completo:* {paciente_nombre_final}\n"
            f"• *Cédula:* {paciente_cedula_final}\n"
            f"• *WhatsApp Paciente:* {paciente_whatsapp_final}\n"
            f"• *ARS / Seguro:* {paciente_ars_final}\n"
            f"• *No. Afiliado:* {numero_afiliado_ars}\n"
            f"• *Tipo de Plan:* {tipo_plan_ars}\n\n"
            "👨‍⚕️ *DATOS DE LA CONSULTA Y DOCTOR:*\n"
            f"• *Doctor:* {nombre_medico_limpio}\n"
            f"• *Centro Médico:* {centro_medico}\n"
            f"• *WhatsApp Consultorio:* {telefono_doctor}\n"
            f"• *Motivo de Consulta:* {motivo_consulta}\n\n"
            "📅 *DETALLES DE FECHA Y HORARIO:*\n"
            f"• *Fecha:* {fecha_formateada}\n"
            f"• *Tanda:* {tanda}\n"
            "• *Modalidad:* Orden de llegada dentro de la tanda.\n"
            "• *Estado:* ⏳ Pendiente de confirmación por recepción del consultorio.\n\n"
            "Recibirás una notificación cuando la secretaria del consultorio confirme la cita."
        )

        return json.dumps({
            "status": "exitoso",
            "mensaje_formateado_final": mensaje_final,
            "cita_id": cita_creada.get("id")
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)})

def consultar_horario_y_bloqueos(medico_master_id: int = 0, medico_nombre: str = "", fecha_consulta: str = "") -> str:
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
        texto_analizar = remover_tildes(f"{nombre_medico} {mensaje_raw}").lower()
        query = supabase.table("vitalmi_directorio_master").select("*", count="exact")

        stop_words = ["doctor", "doctora", "cita", "quiero", "necesito", "con", "del", "esta", "para", "una"]
        tokens = [t for t in re.findall(r'\b\w{3,}\b', texto_analizar) if t not in stop_words]

        if tokens:
            for tok in tokens[:3]:
                query = query.ilike("nombre", f"%{tok}%")

        res = query.limit(20).execute()
        return json.dumps({"total_exacto": len(res.data) if res.data else 0, "medicos_muestra": res.data or []}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

SYSTEM_PROMPT_PACIENTE_REGISTRADO = """
Eres Gema, la asistente virtual médica de VitalMi en República Dominicana.
El usuario con el que hablas YA ESTÁ REGISTRADO en la plataforma (tiene su perfil completo en Supabase).

### 🎯 TU OBJETIVO:
Atender de forma ultra-rápida, concisa y ejecutiva la solicitud de agendamiento de cita del paciente.

### 🚫 REGLAS DE ORO:
1. JAMÁS vuelvas a enviar enlaces a Google Forms ni pidas cédula, ARS ni provincia; esos datos ya están guardados en su perfil.
2. Si el usuario pide agendar con un médico o especialidad:
   - Consulta el directorio con 'consultar_directorio_inteligente'.
   - Solicita ÚNICAMENTE la Fecha deseada y la Tanda (Mañana o Tarde).
3. Sé breve, profesional y directo al punto. Cero rellenos o frases genéricas como "Estoy aquí para ayudarte".
"""

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    # 1. Registrar o recuperar el paciente en Supabase
    paciente = registrar_o_actualizar_paciente(numero_usuario, nombre_usuario)
    
    nombre_contacto = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else nombre_usuario
    if not nombre_contacto or nombre_contacto in ["Trancrédito", "Usuario WhatsApp", "Paciente", ""]:
        nombre_contacto = "JUAN REYES"

    perfil_completo = paciente.get("perfil_completo", False)
    url_form_oficial = "https://docs.google.com/forms/d/e/1FAIpQLSdrp4sSaHzxOli3UlYPbvvZgznovAWxQH1IAXvFi0OveZC_cg/viewform"

    # 2. INTERCEPCIÓN DETERMINISTA DE REGISTRO (SI NO TIENE PERFIL COMPLETO)
    if not perfil_completo:
        respuesta_onboarding = (
            f"Hola {nombre_contacto}, ¿cómo te sientes hoy? Espero que te encuentres bien de salud. "
            f"Para agendar tu cita con mayor rapidez y precisión, esta vez y siempre, necesito que llenes este breve formulario. "
            f"Favor de hacer click en el siguiente enlace:\n\n"
            f"📋 {url_form_oficial}"
        )
        guardar_mensaje_supabase(numero_usuario, "user", mensaje_usuario)
        guardar_mensaje_supabase(numero_usuario, "assistant", respuesta_onboarding)
        return respuesta_onboarding

    # 3. SI EL PACIENTE YA TIENE PERFIL COMPLETO, SE PROCESA CON EL LLM CONVERSACIONAL Y RÁPIDO
    guardar_mensaje_supabase(numero_usuario, "user", mensaje_usuario)
    historial_raw = obtener_historial_supabase(numero_usuario, limite=6)
    historial_limpio = [{"role": m["rol"] if "rol" in m else m["role"], "content": m["contenido"] if "contenido" in m else m["content"]} for m in historial_raw]

    ahora_rd = datetime.now(TZ_RD)
    contexto_temporal = f"\nHoy es {ahora_rd.strftime('%Y-%m-%d %H:%M:%S')} AST en República Dominicana."
    contexto_usuario = f"\nHablas con el paciente registrado '{nombre_contacto}' (WhatsApp ID: {numero_usuario})."
    
    system_prompt = SYSTEM_PROMPT_PACIENTE_REGISTRADO + contexto_temporal + contexto_usuario

    tools = [
        {
            "type": "function",
            "function": {
                "name": "consultar_directorio_inteligente",
                "description": "Consulta en el directorio médico.",
                "parameters": {"type": "object", "properties": {"nombre_medico": {"type": "string"}}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_horario_y_bloqueos",
                "description": "Obtiene las tandas de horarios disponibles.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "agendar_cita_medica",
                "description": "Registra la cita médica utilizando los datos de perfil ya guardados.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medico_nombre": {"type": "string"},
                        "fecha_cita": {"type": "string"},
                        "tanda": {"type": "string"},
                        "motivo_consulta": {"type": "string"}
                    },
                    "required": ["medico_nombre", "fecha_cita", "tanda"]
                }
            }
        }
    ]

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial_limpio)

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
            messages_tool = list(messages)
            messages_tool.append(response_message)

            for tool_call in response_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if name == "consultar_directorio_inteligente":
                    args["mensaje_raw"] = mensaje_usuario
                    res_tool = consultar_directorio_inteligente(**args)
                elif name == "consultar_horario_y_bloqueos":
                    res_tool = consultar_horario_y_bloqueos(**args)
                elif name == "agendar_cita_medica":
                    args["telefono_jid"] = numero_usuario
                    res_tool = agendar_cita_medica(**args)
                else:
                    res_tool = json.dumps({"error": "Herramienta no encontrada"})

                messages_tool.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": name,
                    "content": res_tool
                })

            second_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages_tool,
                temperature=0.0,
                max_tokens=500
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