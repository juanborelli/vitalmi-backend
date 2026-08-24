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

### 🎭 REGLAS DE AGENDAMIENTO Y RESUMEN UNIFICADO:
1. UN PACIENTE PUEDE TENER MÚLTIPLES CITAS EN LA MISMA TANDA Y MISMO DÍA (cada consulta médica dura aprox. 15 minutos).
2. NO Asumas conflictos de horario ni canceles citas automáticamente a menos que el usuario diga explícitamente "quiero cancelar la cita con el Dr. X".
3. Al confirmar una cita exitosa, si el backend reporta citas adicionales para esa misma fecha/tanda, NOTIFICA Y RESUME TODAS LAS CITAS ACTIVAS DEL DÍA EN UN SOLO MENSAJE CONSOLIDADO.

### 🎭 FORMATO OBLIGATORIO DE CONFIRMACIÓN DE CITA:
Estructura tu respuesta de la siguiente manera:
"Cita agendada exitosamente para el/la señor/a **[Nombre del Paciente]** (Cédula: **[Cédula/ID]**), con el doctor **[Nombre del Doctor]** en **[Centro Médico / Clínica]**, para el **[Fecha completa]** en la **[Tanda de la Mañana / Tanda de la Tarde]**.

📋 **Resumen de tus citas para ese día:**
- [Médico 1] | [Centro 1] | [Tanda]
- [Médico 2] | [Centro 2] | [Tanda]

[Despedida amable]"

### 🚫 REGLAS DE ORO:
1. NUNCA ASIGNES HORAS FIJAS FUERA DE TANDA (como "10:00 AM" o "4:00 PM"). Confirma siempre por TANDA ("Tanda de la Mañana a partir de las 9:00 AM" o "Tanda de la Tarde a partir de las 3:00 PM").
2. NUNCA DIGAS "Voy a verificar", "Un momento por favor" ni "Parece que hubo un problema".
3. USA ESTRICTAMENTE EL CALENDARIO INYECTADO PARA SABER LA FECHA EXACTA DE CADA DÍA DE LA SEMANA.
"""

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
        res_pac = supabase.table("pacientes").select("id, nombre, cedula").eq("telefono_jid", telefono_jid).execute()
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
        print(f"❌ Error en consultar_mis_citas: {e}")
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
            "mensaje": f"La cita ha sido actualizada a estado '{nuevo_estado}' correctamente en VitalMi."
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
        nombre_medico_limpio = medico_nombre.strip() if medico_nombre else "Médico General"
        fecha_real_iso = resolver_fecha_relativa(fecha_cita)
        
        fecha_dt = datetime.strptime(fecha_real_iso, "%Y-%m-%d")
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        meses_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        
        nombre_dia = dias_es[fecha_dt.weekday()]
        nombre_mes = meses_es[fecha_dt.month - 1]
        fecha_formateada = f"{nombre_dia} {fecha_dt.day} de {nombre_mes} de {fecha_dt.year}"

        res_pac = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        paciente = res_pac.data[0] if (res_pac.data and len(res_pac.data) > 0) else {}
        paciente_id = paciente.get("id")
        paciente_nombre = paciente.get("nombre", "Paciente")
        
        if paciente_nombre in ["Trancrédito", "Usuario WhatsApp", "Paciente", None]:
            paciente_nombre = "Titular de la cuenta"

        paciente_cedula = paciente.get("cedula", "No registrada")

        centro_medico = "Centro Médico Autorizado"
        res_doc = supabase.table("vitalmi_directorio_master").select("centro_medico").ilike("nombre", f"%{remover_tildes(nombre_medico_limpio)[:6]}%").limit(1).execute()
        if res_doc.data and res_doc.data[0].get("centro_medico"):
            centro_medico = res_doc.data[0].get("centro_medico")

        # Registrar la nueva cita directamente sin restricciones por misma tanda/día
        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Médico: {nombre_medico_limpio} | Centro: {centro_medico} | Tanda: {tanda} | Motivo: {motivo_consulta} | Fecha: {fecha_formateada} ({fecha_real_iso})",
            "estado": "solicitada",
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        # Consultar TODAS las citas activas para esa fecha específica y enviarlas agrupadas
        citas_del_dia = []
        if paciente_id:
            res_todas = supabase.table("citas") \
                .select("motivo_consulta") \
                .eq("paciente_id", paciente_id) \
                .neq("estado", "cancelada") \
                .ilike("motivo_consulta", f"%{fecha_real_iso}%") \
                .execute()
            if res_todas.data:
                citas_del_dia = [c.get("motivo_consulta") for c in res_todas.data]

        return json.dumps({
            "status": "exitoso",
            "mensaje": f"Cita registrada exitosamente con {nombre_medico_limpio} para el {fecha_formateada}.",
            "cita_id": cita_creada.get("id"),
            "detalles": {
                "paciente_nombre": paciente_nombre,
                "paciente_cedula": paciente_cedula,
                "medico": nombre_medico_limpio,
                "centro_medico": centro_medico,
                "fecha_confirmada": fecha_formateada,
                "fecha_iso": fecha_real_iso,
                "tanda": tanda,
                "estado": "solicitada",
                "todas_citas_dia": citas_del_dia
            }
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en agendar_cita_medica: {e}")
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
        texto_analizar = remover_tildes(f"{mensaje_raw} {contexto_previo}").lower()
        query = supabase.table("vitalmi_directorio_master").select("*", count="exact")

        if nombre_medico:
            nom_clean = remover_tildes(nombre_medico).lower().strip()
            tokens = [t for t in nom_clean.split() if len(t) > 2]
            if tokens:
                for tok in tokens:
                    query = query.ilike("nombre", f"%{tok}%")

        res = query.limit(20).execute()
        return json.dumps({"total_exacto": len(res.data) if res.data else 0, "medicos_muestra": res.data or []}, ensure_ascii=False)
    except Exception as e:
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
            if paciente_existente.get("nombre") in ["Paciente", "Usuario WhatsApp", None, "Trancrédito"] and nombre_guardar not in ["Usuario WhatsApp", "Trancrédito"]:
                supabase.table("pacientes").update({
                    "nombre": nombre_guardar,
                    "updated_at": obtener_hora_rd_iso()
                }).eq("telefono_jid", telefono_jid).execute()
                paciente_existente["nombre"] = nombre_guardar
            return paciente_existente

        datos_nuevo = {"telefono_jid": telefono_jid, "nombre": nombre_guardar, "created_at": obtener_hora_rd_iso()}
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
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

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    paciente = registrar_o_actualizar_paciente(numero_usuario, nombre_usuario)
    nombre_contacto = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else "Estimado/a"
    if nombre_contacto in ["Trancrédito", "Usuario WhatsApp", "Paciente"]:
        nombre_contacto = "Estimado/a"

    historial_raw = obtener_historial_supabase(numero_usuario, limite=6)

    ahora_rd = datetime.now(TZ_RD)
    fecha_hoy_str = ahora_rd.strftime("%Y-%m-%d")
    
    ya_saludo_hoy = False
    if historial_raw:
        for m in historial_raw:
            created_at_str = str(m.get("created_at", ""))
            if created_at_str.startswith(fecha_hoy_str):
                ya_saludo_hoy = True
                break

    guardar_mensaje_supabase(numero_usuario, "user", mensaje_usuario)

    historial_limpio = [{"role": m["rol"] if "rol" in m else m["role"], "content": m["contenido"] if "contenido" in m else m["content"]} for m in historial_raw]

    dias_semana_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    
    proximos_dias = []
    for i in range(7):
        dia_futuro = ahora_rd + timedelta(days=i)
        nombre_d = dias_semana_es[dia_futuro.weekday()]
        fecha_f = dia_futuro.strftime("%d de %B de %Y")
        proximos_dias.append(f"- {nombre_d}: {fecha_f}")
    
    tabla_dias_str = "\n".join(proximos_dias)

    hora_actual = ahora_rd.hour
    saludo_tiempo = "buenos días" if 5 <= hora_actual < 12 else ("buenas tardes" if 12 <= hora_actual < 19 else "buenas noches")
    
    if not ya_saludo_hoy:
        instruccion_saludo = (
            f"ES EL PRIMER CONTACTO DEL DÍA ({fecha_hoy_str}). Inicia tu respuesta OBLIGATORIAMENTE con el saludo oficial:\n"
            f"'¡Hola {nombre_contacto}, {saludo_tiempo}! ¿Cómo te sientes? ¿En qué puedo ayudarte hoy? "
            f"Soy Gema de VitalMi, tu asistente para citas médicas en toda República Dominicana.'\n"
        )
    else:
        instruccion_saludo = (
            f"EL USUARIO YA RECIBIÓ EL SALUDO HOY ({fecha_hoy_str}). "
            f"ESTÁ PROHIBIDO VOLVER A SALUDAR O DECIR '¡Hola!' / 'Buenas tardes'. RESPONDE DIRECTAMENTE A LA CONSULTA."
        )

    contexto_temporal = (
        f"\n\n### ⏰ ANCLA TEMPORAL Y CALENDARIO EXACTO DE HOY:\n"
        f"Hoy es {dias_semana_es[ahora_rd.weekday()]}, {ahora_rd.strftime('%d de %B de %Y')}.\n"
        f"Usa ESTA TABLA DE FECHA REAL para saber qué fecha le corresponde a cada día:\n"
        f"{tabla_dias_str}\n\n"
        f"ÚLTIMO MENSAJE DEL USUARIO: '{mensaje_usuario}'.\n"
        f"{instruccion_saludo}\n"
    )
    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    
    system_prompt = SYSTEM_PROMPT_FASE_1 + contexto_temporal + contexto_usuario

    tools = [
        {
            "type": "function",
            "function": {
                "name": "consultar_directorio_inteligente",
                "description": "Consulta sobre la tabla 'vitalmi_directorio_master'.",
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
                "description": "Registra una cita médica formal en Supabase.",
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
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_mis_citas",
                "description": "Muestra las citas activas del usuario.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "gestionar_estado_cita",
                "description": "Cancela la cita médica activa.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cita_id": {"type": "string"},
                        "nuevo_estado": {"type": "string"}
                    },
                    "required": []
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
                elif name == "consultar_mis_citas":
                    res_tool = consultar_mis_citas(telefono_jid=numero_usuario)
                elif name == "gestionar_estado_cita":
                    args["telefono_jid"] = numero_usuario
                    if "nuevo_estado" not in args:
                        args["nuevo_estado"] = "cancelada"
                    res_tool = gestionar_estado_cita(**args)
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