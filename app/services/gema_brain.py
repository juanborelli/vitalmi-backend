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

def verificar_registro_tercero(telefono_tercero: str) -> str:
    """
    Verifica si el número de WhatsApp de un tercero/familiar está registrado en Supabase con perfil completo.
    """
    supabase = obtener_cliente_supabase()
    if not supabase or not telefono_tercero:
        return json.dumps({"registrado": False, "mensaje": "Teléfono inválido o sin datos."})

    telefono_clean = re.sub(r"\D", "", telefono_tercero)
    usuario_jid = f"{telefono_clean}@s.whatsapp.net"

    try:
        res = supabase.table("pacientes").select("id, nombre, perfil_completo, provincia, ars").eq("telefono_jid", usuario_jid).execute()
        if res.data and len(res.data) > 0:
            pac = res.data[0]
            if pac.get("perfil_completo", False):
                return json.dumps({
                    "registrado": True, 
                    "paciente": pac, 
                    "mensaje": f"El paciente {pac.get('nombre')} está registrado y con perfil completo."
                }, ensure_ascii=False)
        
        return json.dumps({
            "registrado": False, 
            "mensaje": f"El número {telefono_clean} no tiene un perfil completo guardado en Supabase."
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

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

def consultar_directorio_inteligente(
    provincia: str = "", 
    municipio_sector: str = "", 
    especialidad: str = "", 
    nombre_medico: str = "", 
    centro_medico_preferido: str = "",
    mensaje_raw: str = ""
) -> str:
    """
    Busca médicos exclusivamente en la tabla 'vitalmi_directorio_master' filtrando
    por provincia, centro médico deseado y especialidad, omitiendo palabras reservadas de tiempo.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        query = supabase.table("vitalmi_directorio_master").select("*")

        stop_words = [
            "manana", "tarde", "noche", "hoy", "lunes", "martes", "miercoles", "jueves", "viernes", 
            "sabado", "domingo", "doctor", "doctora", "cita", "quiero", "necesito", "con", "del", 
            "esta", "para", "una", "este", "por", "favor", "dame", "ninguno", "ellos", "clinica", "centro"
        ]

        texto_limpio = remover_tildes(f"{nombre_medico} {especialidad} {mensaje_raw}").lower()
        tokens = [t for t in re.findall(r'\b\w{3,}\b', texto_limpio) if t not in stop_words]

        # 1. Filtrar por provincia de residencia del paciente
        if provincia:
            query = query.ilike("provincia", f"%{remover_tildes(provincia)}%")

        # 2. Filtrar por Centro Médico si el usuario especificó uno
        if centro_medico_preferido:
            query = query.ilike("centro_medico", f"%{remover_tildes(centro_medico_preferido)}%")

        # 3. Filtrar por coincidencia de especialidad o médico
        if tokens:
            for tok in tokens[:2]:
                query = query.or_(f"nombre.ilike.%{tok}%,especialidad.ilike.%{tok}%")

        res = query.limit(10).execute()
        medicos = res.data or []
        
        if not medicos:
            return json.dumps({
                "total_exacto": 0, 
                "mensaje": f"No se encontraron especialistas en {provincia if provincia else 'la zona'} para los criterios especificados.",
                "medicos_muestra": []
            }, ensure_ascii=False)

        return json.dumps({"total_exacto": len(medicos), "medicos_muestra": medicos}, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en consultar_directorio_inteligente: {e}")
        return json.dumps({"error": str(e)})

def agendar_cita_medica(
    telefono_jid: str, 
    medico_nombre: str, 
    fecha_cita: str, 
    tanda: str, 
    es_para_tercero: bool = False,
    telefono_tercero: str = "",
    motivo_consulta: str = "Consulta General"
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        if not medico_nombre or "ninguno" in medico_nombre.lower():
            return json.dumps({"error": "Debes especificar un médico válido antes de agendar."})

        # Determinar el perfil objetivo (Titular vs Tercero)
        jid_objetivo = telefono_jid
        if es_para_tercero and telefono_tercero:
            tel_clean = re.sub(r"\D", "", telefono_tercero)
            jid_objetivo = f"{tel_clean}@s.whatsapp.net"

        res_pac = supabase.table("pacientes").select("*").eq("telefono_jid", jid_objetivo).execute()
        if not res_pac.data:
            return json.dumps({"error": f"No se encontró el perfil guardado para {jid_objetivo}."})

        paciente = res_pac.data[0]
        paciente_id = paciente.get("id")
        nombre_paciente = paciente.get("nombre", "Paciente")
        cedula_paciente = paciente.get("cedula", "No registrada")
        ars_paciente = paciente.get("ars", "Privado")
        plan_ars = paciente.get("tipo_plan", "Básico")
        afiliado_ars = paciente.get("numero_afiliado", "No especificado")

        fecha_real_iso = resolver_fecha_relativa(fecha_cita)
        fecha_dt = datetime.strptime(fecha_real_iso, "%Y-%m-%d")
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        meses_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        fecha_formateada = f"{dias_es[fecha_dt.weekday()]} {fecha_dt.day} de {meses_es[fecha_dt.month - 1]} de {fecha_dt.year}"

        # Búsqueda de datos del especialista en el directorio
        centro_medico = "Consultorio Privado Autorizado"
        especialidad_medico = "Medicina General"
        
        res_doc = supabase.table("vitalmi_directorio_master").select("*").ilike("nombre", f"%{remover_tildes(medico_nombre)[:6]}%").limit(1).execute()
        if res_doc.data:
            centro_medico = res_doc.data[0].get("centro_medico") or centro_medico
            medico_nombre = res_doc.data[0].get("nombre") or medico_nombre
            especialidad_medico = res_doc.data[0].get("especialidad") or especialidad_medico

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Paciente: {nombre_paciente} | Cédula: {cedula_paciente} | ARS: {ars_paciente} ({plan_ars}, Afiliado: {afiliado_ars}) | Médico: {medico_nombre} ({especialidad_medico}) | Centro: {centro_medico} | Tanda: {tanda} | Fecha: {fecha_formateada} | Motivo: {motivo_consulta}",
            "estado": "pendiente_aprobacion",
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        # PLANTILLA ACTUALIZADA
        mensaje_final = (
            "📋 *SOLICITUD DE CITA REGISTRADA*\n\n"
            "👤 *DATOS DEL PACIENTE:*\n"
            f"• *Nombre:* {nombre_paciente}\n"
            f"• *Cédula:* {cedula_paciente}\n"
            f"• *ARS:* {ars_paciente} ({plan_ars})\n"
            f"• *No. Afiliado:* {afiliado_ars}\n\n"
            "👨‍⚕️ *DATOS DEL ESPECIALISTA:*\n"
            f"• *Doctor:* {medico_nombre}\n"
            f"• *Especialidad:* {especialidad_medico}\n"
            f"• *Centro:* {centro_medico}\n\n"
            "📅 *HORARIO Y DETALLES:*\n"
            f"• *Fecha:* {fecha_formateada}\n"
            f"• *Tanda:* {tanda}\n"
            f"• *Motivo:* {motivo_consulta}\n"
            "• *Estado:* ⏳ Cita pendiente de confirmación por el doctor.\n"
        )

        return json.dumps({
            "status": "exitoso",
            "mensaje_formateado_final": mensaje_final,
            "cita_id": cita_creada.get("id")
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)})

SYSTEM_PROMPT_PACIENTE_REGISTRADO = """
Eres Gema, la asistente médica virtual de VitalMi en República Dominicana.
Hablas con un usuario registrado. Sus datos de perfil principales están en Supabase.

### 🎭 SECUENCIA DE INTERACCIÓN Y MANEJO DE CITAS:

1. ¿PARA QUIÉN ES LA CITA? (Titular vs Tercero):
   - Pregunta si la cita es para el titular o para un tercero (hijo, familiar, amigo).
   - SI ES PARA UN TERCERO: Pide el número de WhatsApp de dicha persona y ejecuta 'verificar_registro_tercero'.
     * Si el tercero NO está registrado (perfil_completo = False), indícale que para agendar a su familiar se requiere llenar por única vez la ficha de registro y envíale el enlace oficial:
       📋 https://docs.google.com/forms/d/e/1FAIpQLSdrp4sSaHzxOli3UlYPbvvZgznovAWxQH1IAXvFi0OveZC_cg/viewform
     * Si el tercero SI está registrado, utiliza los datos de su perfil para continuar.

2. PREGUNTAS DINÁMICAS DE CITA:
   - Especialidad o Médico solicitado.
   - Preferencia de Centro Médico/Clínica (o si prefiere el más cercano a su residencia).
   - Fecha deseada y Tanda (Mañana o Tarde).
   - Motivo de consulta.

3. REGLAS DE BÚSQUEDA Y AGENDAMIENTO:
   - Invocas 'consultar_directorio_inteligente' pasando la especialidad, la provincia del paciente y el centro médico deseado (si lo indicó).
   - NUNCA inventes nombres de médicos que no devuelva la función.
   - Pide al usuario ELEGIR UN DOCTOR ESPECÍFICO de la lista.
   - Solo invocas 'agendar_cita_medica' cuando el doctor, la fecha, la tanda y el beneficiario estén 100% confirmados.
"""

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    paciente = registrar_o_actualizar_paciente(numero_usuario, nombre_usuario)
    
    nombre_contacto = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else nombre_usuario
    if not nombre_contacto or nombre_contacto in ["Trancrédito", "Usuario WhatsApp", "Paciente", ""]:
        nombre_contacto = "JUAN REYES"

    perfil_completo = paciente.get("perfil_completo", False)
    provincia_paciente = paciente.get("provincia", "San Cristóbal")
    municipio_paciente = paciente.get("municipio_sector", "")
    
    url_form_oficial = "https://docs.google.com/forms/d/e/1FAIpQLSdrp4sSaHzxOli3UlYPbvvZgznovAWxQH1IAXvFi0OveZC_cg/viewform"

    # INTERCEPCIÓN DETERMINISTA DE ONBOARDING TITULAR
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

    # PACIENTE REGISTRADO -> PROCESAMIENTO DINÁMICO
    guardar_mensaje_supabase(numero_usuario, "user", mensaje_usuario)
    historial_raw = obtener_historial_supabase(numero_usuario, limite=6)
    historial_limpio = [{"role": m["rol"] if "rol" in m else m["role"], "content": m["contenido"] if "contenido" in m else m["content"]} for m in historial_raw]

    ahora_rd = datetime.now(TZ_RD)
    contexto_temporal = f"\nHoy es {ahora_rd.strftime('%Y-%m-%d %H:%M:%S')} AST en República Dominicana."
    contexto_paciente = (
        f"\nUSUARIO TITULAR: '{nombre_contacto}' | WhatsApp: {numero_usuario}\n"
        f"PROVINCIA REGISTRADA: '{provincia_paciente}', Municipio: '{municipio_paciente}'."
    )
    
    system_prompt = SYSTEM_PROMPT_PACIENTE_REGISTRADO + contexto_temporal + contexto_paciente

    tools = [
        {
            "type": "function",
            "function": {
                "name": "verificar_registro_tercero",
                "description": "Verifica si el número de WhatsApp de un tercero/familiar está registrado en Supabase.",
                "parameters": {
                    "type": "object",
                    "properties": {"telefono_tercero": {"type": "string"}},
                    "required": ["telefono_tercero"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_directorio_inteligente",
                "description": "Busca especialistas en el directorio según ubicación y centro médico deseado.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "especialidad": {"type": "string"},
                        "nombre_medico": {"type": "string"},
                        "provincia": {"type": "string"},
                        "centro_medico_preferido": {"type": "string"}
                    }, 
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "agendar_cita_medica",
                "description": "Registra una cita médica confirmada.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medico_nombre": {"type": "string"},
                        "fecha_cita": {"type": "string"},
                        "tanda": {"type": "string"},
                        "es_para_tercero": {"type": "boolean"},
                        "telefono_tercero": {"type": "string"},
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

                if name == "verificar_registro_tercero":
                    res_tool = verificar_registro_tercero(**args)
                elif name == "consultar_directorio_inteligente":
                    args["mensaje_raw"] = mensaje_usuario
                    if "provincia" not in args or not args["provincia"]:
                        args["provincia"] = provincia_paciente
                    res_tool = consultar_directorio_inteligente(**args)
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
        return "Tuve un inconveniente técnico procesando tu solicitud. Por favor indícame la especialidad o doctor que buscas."

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)