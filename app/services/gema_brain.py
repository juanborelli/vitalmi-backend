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

### 🎭 ESQUEMA DE RECOLECCIÓN DE DATOS OBLIGATORIOS (SECTOR PRIVADO RD):
Si el usuario desea agendar una cita, verifica y solicita amablemente los datos faltantes:
1. **Datos del Seguro (ARS):** Nombre de la ARS, Número de Afiliado (carnet) y Tipo de Plan (Básico, Ejecutivo, etc., o 'Privado').
2. **Datos Personales:** Nombre Completo del paciente, Cédula y Teléfono/WhatsApp.
3. **Datos de Consulta:** Médico, Fecha, Tanda y Motivo (Primera visita, Chequeo de rutina, Lectura de resultados).

### 🎭 CONFIRMACIÓN DE CITA:
Cuando llames a 'agendar_cita_medica', UTILIZA DIRECTAMENTE EL TEXTO EN 'mensaje_formateado_final' para responder. Queda PROHIBIDO generar textos con corchetes como '[Nombre del Doctor]'.

### 🚫 REGLAS DE ORO:
1. NUNCA ASIGNES HORAS FIJAS FUERA DE TANDA. Confirma siempre por TANDA ("Tanda de la Mañana" o "Tanda de la Tarde").
2. NO VUELVAS A PREGUNTAR por datos que el usuario ya proporcionó en mensajes anteriores.
3. EXPLICAR SIEMPRE QUE EL INGRESO A CONSULTORIO ES POR ORDEN DE LLEGADA DENTRO DE LA TANDA ASIGNADA.
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

def extraer_datos_mensaje(texto: str) -> dict:
    texto_clean = remover_tildes(texto).lower()
    
    # Cédula (11 dígitos)
    numeros = re.sub(r'\D', '', texto)
    match_cedula = re.search(r'\b\d{11}\b', numeros)
    cedula = match_cedula.group(0) if match_cedula else ""

    # ARS y Afiliado
    ars = ""
    aseguradoras = ["mapfre", "humano", "senasa", "palic", "universal", "monumental", "sigma", "renacer", "simag"]
    for a in aseguradoras:
        if a in texto_clean:
            ars = a.capitalize() if a != "senasa" else "SeNaSa"
            break
    if not ars and ("sin seguro" in texto_clean or "privado" in texto_clean or "no tengo" in texto_clean):
        ars = "Privado"

    # Tanda
    tanda = ""
    if "manana" in texto_clean or "matutina" in texto_clean:
        tanda = "Tanda de la Mañana"
    elif "tarde" in texto_clean or "vespertina" in texto_clean:
        tanda = "Tanda de la Tarde"

    return {"cedula": cedula, "ars": ars, "tanda": tanda}

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

        if not es_para_tercero and paciente_id:
            actualizaciones = {}
            if cedula_paciente.strip():
                actualizaciones["cedula"] = cedula_paciente.strip()
            if ars_paciente.strip():
                actualizaciones["ars"] = ars_paciente.strip()
            if actualizaciones:
                supabase.table("pacientes").update(actualizaciones).eq("id", paciente_id).execute()

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

    datos_extraidos = extraer_datos_mensaje(mensaje_usuario)
    
    supabase = obtener_cliente_supabase()
    actualizaciones_pac = {}
    
    if datos_extraidos["cedula"]:
        actualizaciones_pac["cedula"] = datos_extraidos["cedula"]
        paciente["cedula"] = datos_extraidos["cedula"]
    if datos_extraidos["ars"]:
        actualizaciones_pac["ars"] = datos_extraidos["ars"]
        paciente["ars"] = datos_extraidos["ars"]

    if actualizaciones_pac and supabase and paciente.get("id"):
        supabase.table("pacientes").update(actualizaciones_pac).eq("id", paciente.get("id")).execute()

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
        f"Hoy es {dias_semana_es[ahora_rd.weekday()]}, {ahora_rd.strftime('%d de %B de %Y')} (Hora actual: {ahora_rd.strftime('%I:%M %p')}).\n"
        f"Usa ESTA TABLA DE FECHA REAL para saber qué fecha le corresponde a cada día:\n"
        f"{tabla_dias_str}\n\n"
        f"DATOS CONFIRMADOS DEL PACIENTE EN SISTEMA:\n"
        f"- Cédula registrada: {paciente.get('cedula', 'No registrada')}\n"
        f"- ARS registrada: {paciente.get('ars', 'No registrada')}\n"
        f"- Tanda detectada en último mensaje: {datos_extraidos['tanda'] or 'No especificada'}\n\n"
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
                "description": "Registra la solicitud de cita médica privada en Supabase capturando ficha del seguro y del paciente.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medico_nombre": {"type": "string"},
                        "fecha_cita": {"type": "string"},
                        "tanda": {"type": "string"},
                        "es_para_tercero": {"type": "boolean"},
                        "nombre_paciente_tercero": {"type": "string"},
                        "telefono_paciente_tercero": {"type": "string"},
                        "cedula_paciente": {"type": "string"},
                        "ars_paciente": {"type": "string"},
                        "numero_afiliado_ars": {"type": "string", "description": "Número de carnet de afiliado a la ARS"},
                        "tipo_plan_ars": {"type": "string", "description": "Plan del seguro: Básico, Ejecutivo, Premium, Privado"},
                        "motivo_consulta": {"type": "string", "description": "Primera visita, chequeo de rutina, entrega de resultados"}
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
                    if paciente.get("cedula") and not args.get("cedula_paciente"):
                        args["cedula_paciente"] = paciente.get("cedula")
                    if paciente.get("ars") and not args.get("ars_paciente"):
                        args["ars_paciente"] = paciente.get("ars")
                    if datos_extraidos["tanda"] and not args.get("tanda"):
                        args["tanda"] = datos_extraidos["tanda"]
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
            
            res_json = json.loads(res_tool) if (name == "agendar_cita_medica" and res_tool.startswith("{")) else {}
            if res_json.get("mensaje_formateado_final"):
                respuesta_texto = res_json.get("mensaje_formateado_final")
            else:
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