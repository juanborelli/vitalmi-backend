import os
import re
import json
import logging
from datetime import datetime, timedelta
import zoneinfo
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Importar las herramientas modulares
from app.services.directory_tools import buscar_directorio_salud, buscar_hospitales_emergencia
from app.core.supabase import obtener_cliente_supabase

# Importar funciones de Evolution Service con protección fallback
try:
    from app.services.evolution_service import enviar_mensaje_whatsapp, verificar_numero_whatsapp
except ImportError:
    def enviar_mensaje_whatsapp(jid: str, texto: str) -> dict:
        return {"success": False, "error": "enviar_mensaje_whatsapp no encontrado"}
    def verificar_numero_whatsapp(jid: str) -> bool:
        return True

# Configuración de Logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("GemaBrain")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path, override=True)

TZ_RD = zoneinfo.ZoneInfo("America/Santo_Domingo")
URL_FORM_OFICIAL = "https://docs.google.com/forms/d/e/1FAIpQLSdrp4sSaHzxOli3UlYPbvvZgznovAWxQH1IAXvFi0OveZC_cg/viewform"

# ==========================================
# FUNCIONES DE UTILIDAD
# ==========================================

def obtener_cliente_openai() -> Optional[AsyncOpenAI]:
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
    if not texto: return ""
    replacements = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("ñ", "n"), ("Ñ", "N"))
    for a, b in replacements:
        texto = texto.replace(a, b)
    return texto.strip().lower()

def extraer_primer_nombre_valido(nombre_raw: str) -> str:
    if not nombre_raw: return ""
    palabras = [p.capitalize() for p in nombre_raw.split() if len(p) > 2 and p.lower() not in ["del", "las", "los", "san", "santa", "usuario", "whatsapp"]]
    return palabras[0] if palabras else ""

def normalizar_jid(telefono_raw: str) -> str:
    if not telefono_raw: return ""
    solo_numeros = re.sub(r"\D", "", telefono_raw)
    if len(solo_numeros) == 10: solo_numeros = f"1{solo_numeros}"
    elif len(solo_numeros) > 11 and solo_numeros.startswith("1"): solo_numeros = solo_numeros[:11]
    return f"{solo_numeros}@s.whatsapp.net"

# ==========================================
# GESTIÓN DE BASE DE DATOS Y CHAT
# ==========================================

def obtener_o_registrar_paciente_por_whatsapp(telefono_jid: str, nombre_push: str = "") -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase: return {}
    try:
        jid_normalizado = normalizar_jid(telefono_jid)
        res = supabase.table("pacientes").select("*").eq("telefono_jid", jid_normalizado).execute()
        if res.data and len(res.data) > 0:
            paciente_existente = res.data[0]
            if nombre_push and (paciente_existente.get("nombre") in ["", "Usuario WhatsApp", None]):
                supabase.table("pacientes").update({"nombre": nombre_push.strip()}).eq("id", paciente_existente["id"]).execute()
                paciente_existente["nombre"] = nombre_push.strip()
            return paciente_existente

        nombre_inicial = nombre_push.strip() or "Usuario WhatsApp"
        res_insert = supabase.table("pacientes").insert({
            "telefono_jid": jid_normalizado, "nombre": nombre_inicial, "perfil_completo": False, "created_at": obtener_hora_rd_iso()
        }).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
        logger.error(f"❌ Error identificando paciente: {e}")
        return {}

def obtener_historial_supabase(telefono_jid: str, limite: int = 6) -> List[Dict[str, str]]:
    supabase = obtener_cliente_supabase()
    if not supabase: return []
    try:
        response = supabase.table("historial_chats").select("rol, contenido, created_at").eq("telefono_jid", normalizar_jid(telefono_jid)).order("created_at", desc=True).limit(limite).execute()
        return response.data[::-1] if response.data else []
    except Exception:
        return []

def guardar_mensaje_supabase(telefono_jid: str, rol: str, contenido: str, tipo_mensaje: str = "texto"):
    supabase = obtener_cliente_supabase()
    if not supabase: return
    try:
        supabase.table("historial_chats").insert({
            "telefono_jid": normalizar_jid(telefono_jid), "rol": rol, "contenido": contenido, "tipo_mensaje": tipo_mensaje, "created_at": obtener_hora_rd_iso()
        }).execute()
    except Exception as e:
        logger.error(f"❌ Error guardando mensaje: {e}")

# ==========================================
# AGENDAMIENTO Y NOTIFICACIONES
# ==========================================

def despachar_notificacion_doctor(cita_id: str) -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase: return {"status": "error", "mensaje": "Sin conexión", "mensaje_doctor_texto": ""}

    res_cita = supabase.table("citas").select("*").eq("id", cita_id).execute()
    if not res_cita.data: return {"status": "error", "mensaje": "Cita no encontrada", "mensaje_doctor_texto": ""}

    cita = res_cita.data[0]
    doc_jid = cita.get("doctor_whatsapp_jid")
    motivo_raw = cita.get("motivo_consulta", "")
    medico_nombre = "Doctor"
    
    if "|" in motivo_raw:
        for p in motivo_raw.split("|"):
            if "Médico:" in p: medico_nombre = p.replace("Médico:", "").strip()

    if not doc_jid and medico_nombre:
        res_doc = supabase.table("vitalmi_directorio_master").select("telefono_institucional, whatsapp").ilike("nombre", f"%{medico_nombre.split()[0]}%").limit(1).execute()
        if res_doc.data:
            sec_phone = res_doc.data[0].get("whatsapp") or res_doc.data[0].get("telefono_institucional")
            if sec_phone: doc_jid = normalizar_jid(sec_phone)

    mensaje_doctor = (
        f"Estimado(a) {medico_nombre},\n\nSoy Gema, la asistente inteligente para citas médicas de VitalMi.\n\n"
        f"📝 *NUEVA SOLICITUD DE CITA:*\n• *Paciente:* {cita.get('motivo_consulta')}\n• *Costo Estimado:* RD$ {cita.get('costo_consulta', 2500):,.2f}\n\n"
        "Por favor responda a este mensaje con:\n✅ *CONFIRMAR* - Para aceptar la cita.\n❌ *RECHAZAR* - Para indicar que no hay disponibilidad."
    )

    if not doc_jid:
        supabase.table("citas").update({"whatsapp_status": "fallido_sin_numero"}).eq("id", cita_id).execute()
        return {"status": "fallido", "error": "Sin número de WhatsApp", "mensaje_doctor_texto": mensaje_doctor}

    try:
        res_envio = enviar_mensaje_whatsapp(doc_jid, mensaje_doctor)
        if res_envio and (res_envio.get("success") or res_envio.get("status") in ["success", 200]):
            msg_id = res_envio.get("message_id") or res_envio.get("id") or res_envio.get("key", {}).get("id")
            supabase.table("citas").update({"doctor_whatsapp_jid": doc_jid, "whatsapp_msg_id": msg_id, "whatsapp_status": "enviado", "updated_at": obtener_hora_rd_iso()}).eq("id", cita_id).execute()
            return {"status": "exitoso", "jid_destinatario": doc_jid, "mensaje_doctor_texto": mensaje_doctor}
    except Exception as err_api:
        logger.error(f"❌ Error enviando WhatsApp: {err_api}")
        
    supabase.table("citas").update({"whatsapp_status": "fallido_envio"}).eq("id", cita_id).execute()
    return {"status": "fallido", "error": "Falló el envío de la API", "mensaje_doctor_texto": mensaje_doctor}

def agendar_cita_medica(telefono_jid: str, medico_nombre: str, fecha_cita: str = "Mañana", tanda: str = "Mañana", es_para_tercero: bool = False, telefono_tercero: str = "", motivo_consulta: str = "Consulta General") -> str:
    supabase = obtener_cliente_supabase()
    if not supabase: return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        jid_objetivo = normalizar_jid(telefono_tercero) if es_para_tercero and telefono_tercero else normalizar_jid(telefono_jid)
        res_pac = supabase.table("pacientes").select("*").eq("telefono_jid", jid_objetivo).execute()
        
        if not res_pac.data or not res_pac.data[0].get("perfil_completo", False):
            return json.dumps({
                "error": "perfil_incompleto",
                "mensaje": f"Para poder agendar y confirmar formalmente tu cita médica con el doctor, necesitamos que completes tus datos en nuestro formulario oficial de registro: {URL_FORM_OFICIAL}\n\nUna vez completado, confírmame por aquí y con gusto agendamos tu cita."
            }, ensure_ascii=False)

        paciente = res_pac.data[0]
        centro_medico = "Consultorio Privado Autorizado"
        doc_whatsapp = ""

        tokens_nombre = [t for t in remover_tildes(medico_nombre).split() if len(t) > 3]
        if tokens_nombre:
            res_doc = supabase.table("vitalmi_directorio_master").select("*").ilike("nombre", f"%{tokens_nombre[0]}%").limit(1).execute()
            if res_doc.data:
                doc_data = res_doc.data[0]
                centro_medico = doc_data.get("centro_medico") or centro_medico
                medico_nombre = doc_data.get("nombre") or medico_nombre
                doc_whatsapp = doc_data.get("whatsapp") or doc_data.get("telefono_institucional") or ""

        datos_cita = {
            "paciente_id": paciente.get("id"),
            "motivo_consulta": f"Paciente: {paciente.get('nombre')} | Cédula: {paciente.get('cedula', 'N/A')} | ARS: {paciente.get('ars', 'Privado')} | Médico: {medico_nombre} | Centro: {centro_medico} | Motivo: {motivo_consulta}",
            "estado": "pendiente_aprobacion",
            "doctor_whatsapp_jid": normalizar_jid(doc_whatsapp) if doc_whatsapp else None,
            "whatsapp_status": "pendiente",
            "costo_consulta": 2500.00,
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        copia_notif = ""
        if cita_creada.get("id"):
            try:
                copia_notif = despachar_notificacion_doctor(cita_creada["id"]).get("mensaje_doctor_texto", "")
            except Exception as err_notif:
                logger.error(f"⚠️ Error al despachar: {err_notif}")

        mensaje_final = f"Tu cita ha sido agendada exitosamente. Estamos enviando tu solicitud al {medico_nombre}.\n\nCopia del mensaje enviado:\n\"{copia_notif}\""
        return json.dumps({"status": "exitoso", "mensaje_formateado_final": mensaje_final, "cita_id": cita_creada.get("id")}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Error agendando cita: {e}")
        return json.dumps({"error": str(e)})

# ==========================================
# CEREBRO GEMA (SYSTEM PROMPT CÁLIDO E INTELIGENTE)
# ==========================================

SYSTEM_PROMPT_GEMA = """
Eres Gema, la asistente virtual oficial de salud de VitalMi en la República Dominicana. 
Tu tono es cálido, humano, empático, profesional y muy servicial. 

ENFOQUE EXCLUSIVO:
Te especializas únicamente en dos cosas de manera impecable:
1. Buscar médicos, especialistas, centros médicos, hospitales y farmacias en el directorio nacional.
2. Agendar y gestionar citas médicas con los profesionales de la salud.

REGLAS DE INTERACCIÓN Y SALUDO (ESTRICTO):
1. **SALUDO INICIAL (ÚNICO):** Si el historial de chat está vacío o es el comienzo de una nueva conversación, saluda de manera cálida y personalizada usando el nombre del usuario (ej: "¡Hola, [Nombre]! ¿Cómo te sientes hoy? Espero que estés muy bien de salud. Soy Gema, tu asistente inteligente para citas médicas. También te puedo ayudar a localizar centros médicos, hospitales y farmacias en todo el país. Estoy aquí lista para servirte.").
2. **MENSAJES SUBSIGUIENTES:** **NUNCA** vuelvas a dar el saludo largo de presentación si ya se saludó en la conversación previa. Ve directo al grano con un tono cercano (ej: "¡Hola, [Nombre]! Qué bueno que estás por aquí de nuevo. ¿En qué puedo ayudarte?").

PROTOCOLOS:
1. **PROTOCOLO DE CRISIS (Emergencias):** Si mencionan "emergencia", "infarto", "accidente" o peligro de muerte, recomienda llamar al 911 de inmediato y usa `buscar_hospitales_emergencia`.
2. **PROTOCOLO DE BÚSQUEDA (Directorio):** 
   - Si buscan médicos/servicios sin especificar zona (ej: "Necesito un urólogo"), **no des listas revueltas nacionales**. Saluda con cercanía y pregúntale amablemente en qué provincia, ciudad o sector prefiere buscar.
   - Si indican zona (ej: "en Naco"), ejecútalo con `buscar_directorio_salud`.
3. **PROTOCOLO DE ACCIÓN (Agendar Citas):** Ejecuta `agendar_cita_medica` cuando el usuario quiera formalizar una cita.

Sé natural, cercana y evita respuestas frías o robóticas.
"""

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client: return "Hola, soy Gema de VitalMi. En este momento estamos actualizando nuestro sistema. Escríbeme en un momentito por favor."

    jid_normalizado = normalizar_jid(numero_usuario)
    paciente = obtener_o_registrar_paciente_por_whatsapp(jid_normalizado, nombre_usuario)
    
    nombre_contacto = extraer_primer_nombre_valido(paciente.get("nombre") or nombre_usuario) or "amigo(a)"
    
    guardar_mensaje_supabase(jid_normalizado, "user", mensaje_usuario)
    historial_raw = obtener_historial_supabase(jid_normalizado, limite=6)
    
    # Determinar si es el primer mensaje (historial vacío o solo el mensaje actual que acabamos de guardar)
    es_primer_mensaje = len(historial_raw) <= 1
    
    historial_limpio = [{"role": m["rol"], "content": m["contenido"]} for m in historial_raw[:-1]] if not es_primer_mensaje else []
    
    contexto = f"\n\n🕒 Fecha actual: {datetime.now(TZ_RD).strftime('%Y-%m-%d %H:%M')}\n👤 Usuario: {nombre_contacto}\n📌 ¿Es el primer saludo?: {'Sí, debes dar la bienvenida completa' if es_primer_mensaje else 'No, ya fue saludado, ve directo al grano'}"
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "buscar_directorio_salud",
                "description": "Busca profesionales o entidades médicas en el directorio nacional. Solo ejecútala si tienes ubicación clara.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "ubicacion": {"type": "string", "description": "Sector, municipio o provincia. Vacío si el usuario no especificó zona."},
                        "tipo_busqueda": {"type": "string", "enum": ["medico", "centro", "farmacia", "nombre_especifico"]},
                        "termino": {"type": "string", "description": "Especialidad o nombre."}
                    }, 
                    "required": ["ubicacion", "tipo_busqueda"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "buscar_hospitales_emergencia",
                "description": "Busca hospitales y clínicas de emergencia.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "ubicacion": {"type": "string", "description": "Ubicación de la emergencia."}
                    }, 
                    "required": ["ubicacion"]
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

    messages = [{"role": "system", "content": SYSTEM_PROMPT_GEMA + contexto}]
    messages.extend(historial_limpio)
    messages.append({"role": "user", "content": mensaje_usuario})

    try:
        response = await client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools, tool_choice="auto", temperature=0.3)
        response_message = response.choices[0].message

        if response_message.tool_calls:
            messages.append(response_message)
            for tool_call in response_message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if name == "buscar_directorio_salud":
                    res_tool = buscar_directorio_salud(**args)
                elif name == "buscar_hospitales_emergencia":
                    res_tool = buscar_hospitales_emergencia(**args)
                elif name == "agendar_cita_medica":
                    res_tool = agendar_cita_medica(telefono_jid=jid_normalizado, **args)
                else:
                    res_tool = json.dumps({"error": "Herramienta desconocida"})

                messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": name, "content": res_tool})

            second_response = await client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.3)
            respuesta_texto = second_response.choices[0].message.content.strip()
        else:
            respuesta_texto = response_message.content.strip()

        guardar_mensaje_supabase(jid_normalizado, "assistant", respuesta_texto)
        return respuesta_texto

    except Exception as e:
        logger.error(f"❌ Error en GemaBrain: {e}")
        return f"Disculpa {nombre_contacto}, he tenido un pequeño inconveniente técnico. ¿En qué te puedo ayudar?"

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)