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

from app.core.supabase import obtener_cliente_supabase

# Importar funciones de Evolution Service
try:
    from app.services.evolution_service import enviar_mensaje_whatsapp
except ImportError:
    def enviar_mensaje_whatsapp(jid: str, texto: str) -> dict:
        return {"success": False, "error": "enviar_mensaje_whatsapp no encontrado"}

try:
    from app.services.evolution_service import verificar_numero_whatsapp
except ImportError:
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
    if not texto:
        return ""
    replacements = (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
        ("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"), ("ñ", "n"), ("Ñ", "N")
    )
    for a, b in replacements:
        texto = texto.replace(a, b)
    return texto.strip()

def extraer_primer_nombre_valido(nombre_raw: str) -> str:
    if not nombre_raw:
        return "Usuario"
    palabras = [p.capitalize() for p in nombre_raw.split() if len(p) > 2 and p.lower() not in ["del", "las", "los", "san", "santa"]]
    return palabras[0] if palabras else "Usuario"

def normalizar_jid(telefono_raw: str) -> str:
    if not telefono_raw:
        return ""
    solo_numeros = re.sub(r"\D", "", telefono_raw)
    if len(solo_numeros) == 10:
        solo_numeros = f"1{solo_numeros}"
    elif len(solo_numeros) > 11 and solo_numeros.startswith("1"):
        solo_numeros = solo_numeros[:11]
    return f"{solo_numeros}@s.whatsapp.net"

def resolver_fecha_relativa(texto_fecha: str) -> str:
    ahora_rd = datetime.now(TZ_RD)
    texto_clean = remover_tildes(str(texto_fecha)).lower().strip()

    if re.match(r"^\d{4}-\d{2}-\d{2}$", texto_clean):
        return texto_clean

    if "manana" in texto_clean or "mañana" in texto_clean:
        return (ahora_rd + timedelta(days=1)).strftime("%Y-%m-%d")

    if "hoy" in texto_clean:
        return ahora_rd.strftime("%Y-%m-%d")

    dias_semana_map = {
        "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
        "viernes": 4, "sabado": 5, "domingo": 6
    }

    for nombre_dia, idx_target in dias_semana_map.items():
        if nombre_dia in texto_clean:
            dias_diferencia = (idx_target - ahora_rd.weekday()) % 7
            if dias_diferencia == 0 or "proximo" in texto_clean or "que viene" in texto_clean:
                dias_diferencia += 7
            fecha_calculada = ahora_rd + timedelta(days=dias_diferencia)
            return fecha_calculada.strftime("%Y-%m-%d")

    return (ahora_rd + timedelta(days=1)).strftime("%Y-%m-%d")

def registrar_o_actualizar_paciente(telefono_jid: str, nombre_push: str = "") -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return {}

    try:
        jid_normalizado = normalizar_jid(telefono_jid)
        res = supabase.table("pacientes").select("*").eq("telefono_jid", jid_normalizado).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]

        datos_nuevo = {
            "telefono_jid": jid_normalizado, 
            "nombre": nombre_push.strip() or "Usuario WhatsApp", 
            "perfil_completo": False,
            "created_at": obtener_hora_rd_iso()
        }
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
        logger.error(f"❌ Error registrando paciente: {e}")
        return {}

def obtener_historial_supabase(telefono_jid: str, limite: int = 10) -> List[Dict[str, str]]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return []

    try:
        jid_norm = normalizar_jid(telefono_jid)
        response = (
            supabase.table("historial_chats")
            .select("rol, contenido, created_at")
            .eq("telefono_jid", jid_norm)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        return response.data[::-1] if response.data else []
    except Exception as e:
        return []

def guardar_mensaje_supabase(telefono_jid: str, rol: str, contenido: str, tipo_mensaje: str = "texto"):
    supabase = obtener_cliente_supabase()
    if not supabase:
        return

    try:
        jid_norm = normalizar_jid(telefono_jid)
        supabase.table("historial_chats").insert({
            "telefono_jid": jid_norm,
            "rol": rol,
            "contenido": contenido,
            "tipo_mensaje": tipo_mensaje,
            "created_at": obtener_hora_rd_iso()
        }).execute()
    except Exception as e:
        logger.error(f"❌ Error guardando mensaje: {e}")

# ==========================================
# DIRECTORIO MASTER - FILTRADO ESTRICTO GEOGRÁFICO
# ==========================================

def consultar_directorio_inteligente(
    especialidad: str = "", 
    ubicacion: str = "", 
    centro_medico: str = "",
    nombre_medico: str = "",
    mensaje_raw: str = ""
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        texto_unificado = remover_tildes(f"{especialidad} {nombre_medico} {mensaje_raw}").lower()
        
        # Mapeo de Especialidad
        tok_esp = ""
        for r in ["urol", "cardio", "pediat", "ginec", "derma", "oftalmo", "ortop", "odont", "general", "interna", "neurol", "psiquia"]:
            if r in texto_unificado:
                tok_esp = r
                break

        # Extraer tokens de ubicación solicitados por el usuario
        raw_ubi = remover_tildes(f"{ubicacion} {centro_medico} {mensaje_raw}").lower()
        ignore_words = [
            "hola", "gema", "necesito", "un", "una", "cardiologo", "urologo", "pediatra", 
            "medico", "doctor", "doctora", "oftalmologo", "ortopeda", "internista", "general", 
            "cerca", "de", "en", "para", "el", "la", "los", "las", "distrito", "nacional"
        ]
        tokens_ubi = [t for t in re.findall(r'\b\w{3,}\b', raw_ubi) if t not in ignore_words and t not in tok_esp]

        logger.info(f"🔍 CONSULTA STRICTA: Especialidad='{tok_esp}' | Tokens Ubicación={tokens_ubi}")

        # Consulta base en Supabase
        query = supabase.table("vitalmi_directorio_master").select("*")
        if tok_esp:
            query = query.ilike("especialidad", f"%{tok_esp}%")

        res = query.limit(150).execute()
        registros = res.data or []

        if not registros:
            return json.dumps({"total_exacto": 0, "medicos_muestra": []}, ensure_ascii=False)

        # FILTRADO DE HIERRO: Exigir que TODOS los tokens de la ciudad/sector estén en el registro
        if tokens_ubi:
            medicos_filtrados = []
            for r in registros:
                p_str = remover_tildes(r.get('provincia', '')).lower()
                m_str = remover_tildes(r.get('municipio', '')).lower()
                d_str = remover_tildes(r.get('direccion', '')).lower()
                c_str = remover_tildes(r.get('centro_medico', '')).lower()

                bloque_total = f"{p_str} {m_str} {d_str} {c_str}"

                # Match ESTRICTO: Cada token de ubicación especificado debe existir en el registro
                if all(t in bloque_total for t in tokens_ubi):
                    medicos_filtrados.append(r)

            medicos_finales = medicos_filtrados[:5]
        else:
            medicos_finales = registros[:5]

        return json.dumps({
            "total_exacto": len(medicos_finales),
            "medicos_muestra": medicos_finales
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Error en consultar_directorio_inteligente: {e}")
        return json.dumps({"error": str(e)})

# ==========================================
# AGENDAMIENTO Y NOTIFICACIONES
# ==========================================

def despachar_notificacion_doctor(cita_id: str) -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return {"status": "error", "mensaje": "Sin conexión a base de datos", "mensaje_doctor_texto": ""}

    res_cita = supabase.table("citas").select("*").eq("id", cita_id).execute()
    if not res_cita.data:
        return {"status": "error", "mensaje": "Cita no encontrada", "mensaje_doctor_texto": ""}

    cita = res_cita.data[0]
    doc_jid = cita.get("doctor_whatsapp_jid")
    
    motivo_raw = cita.get("motivo_consulta", "")
    medico_nombre = "Doctor"
    if "|" in motivo_raw:
        partes = motivo_raw.split("|")
        for p in partes:
            if "Médico:" in p:
                medico_nombre = p.replace("Médico:", "").strip()

    whatsapp_valido = False
    if doc_jid:
        try:
            whatsapp_valido = verificar_numero_whatsapp(doc_jid)
        except Exception as e:
            logger.warning(f"⚠️ Error verificando WhatsApp del doctor: {e}")

    if not whatsapp_valido and medico_nombre:
        res_doc = supabase.table("vitalmi_directorio_master").select("telefono, whatsapp").ilike("nombre", f"%{medico_nombre.split()[0]}%").limit(1).execute()
        if res_doc.data:
            sec_phone = res_doc.data[0].get("whatsapp") or res_doc.data[0].get("telefono")
            if sec_phone:
                doc_jid = normalizar_jid(sec_phone)

    mensaje_doctor = (
        f"Estimado(a) {medico_nombre},\n\n"
        "Soy Gema, la asistente inteligente para citas médicas de VitalMi.\n\n"
        f"📝 *NUEVA SOLICITUD DE CITA:*\n"
        f"• *Paciente:* {cita.get('motivo_consulta')}\n"
        f"• *Costo Estimado:* RD$ {cita.get('costo_consulta', 2500):,.2f}\n\n"
        "Por favor responda a este mensaje con:\n"
        "✅ *CONFIRMAR* - Para aceptar la cita.\n"
        "❌ *RECHAZAR* - Para indicar que no hay disponibilidad."
    )

    if not doc_jid:
        supabase.table("citas").update({"whatsapp_status": "fallido_sin_numero"}).eq("id", cita_id).execute()
        return {"status": "fallido", "error": "Sin número de WhatsApp válido", "mensaje_doctor_texto": mensaje_doctor}

    try:
        res_envio = enviar_mensaje_whatsapp(doc_jid, mensaje_doctor)
    except Exception as err_api:
        logger.error(f"❌ Error llamando a enviar_mensaje_whatsapp: {err_api}")
        res_envio = None
    
    if res_envio and (res_envio.get("success") or res_envio.get("status") in ["success", 200]):
        msg_id = res_envio.get("message_id") or res_envio.get("id") or res_envio.get("key", {}).get("id")
        supabase.table("citas").update({
            "doctor_whatsapp_jid": doc_jid,
            "whatsapp_msg_id": msg_id,
            "whatsapp_status": "enviado",
            "updated_at": obtener_hora_rd_iso()
        }).eq("id", cita_id).execute()
        
        return {"status": "exitoso", "jid_destinatario": doc_jid, "message_id": msg_id, "mensaje_doctor_texto": mensaje_doctor}
    else:
        supabase.table("citas").update({"whatsapp_status": "fallido_envio"}).eq("id", cita_id).execute()
        return {"status": "fallido", "error": "Falló el envío de la API", "mensaje_doctor_texto": mensaje_doctor}

def agendar_cita_medica(
    telefono_jid: str, 
    medico_nombre: str, 
    fecha_cita: str = "Mañana", 
    tanda: str = "Mañana", 
    es_para_tercero: bool = False,
    telefono_tercero: str = "",
    motivo_consulta: str = "Consulta General"
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        jid_objetivo = normalizar_jid(telefono_jid)
        if es_para_tercero and telefono_tercero:
            jid_objetivo = normalizar_jid(telefono_tercero)

        res_pac = supabase.table("pacientes").select("*").eq("telefono_jid", jid_objetivo).execute()
        if not res_pac.data or not res_pac.data[0].get("perfil_completo", False):
            return json.dumps({
                "error": "perfil_incompleto",
                "mensaje": f"Para confirmar esta cita, la persona requiere estar registrada. Favor de completar el formulario en este enlace: {URL_FORM_OFICIAL}"
            }, ensure_ascii=False)

        paciente = res_pac.data[0]
        paciente_id = paciente.get("id")
        nombre_paciente = paciente.get("nombre", "Paciente")
        cedula_paciente = paciente.get("cedula", "No registrada")
        ars_paciente = paciente.get("ars", "Privado")
        plan_ars = paciente.get("tipo_plan", "Básico")

        fecha_real_iso = resolver_fecha_relativa(fecha_cita)
        try:
            fecha_dt = datetime.strptime(fecha_real_iso, "%Y-%m-%d")
            dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            meses_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
            fecha_formateada = f"{dias_es[fecha_dt.weekday()]} {fecha_dt.day} de {meses_es[fecha_dt.month - 1]} de {fecha_dt.year}"
        except Exception:
            fecha_formateada = fecha_cita

        tanda_clean = remover_tildes(tanda).lower()
        if "sabado" in tanda_clean or "sábado" in tanda_clean:
            tanda_texto = "Sábados (9:00 AM – 2:00 PM)"
        elif "tarde" in tanda_clean:
            tanda_texto = "Tarde (3:00 PM – 6:00 PM)"
        else:
            tanda_texto = "Mañana (9:00 AM – 12:00 PM)"

        centro_medico = "Consultorio Privado Autorizado"
        costo_consulta = 2500.00
        doc_whatsapp = ""

        tokens_nombre = [t for t in remover_tildes(medico_nombre).split() if len(t) > 3]
        if tokens_nombre:
            res_doc = supabase.table("vitalmi_directorio_master").select("*").ilike("nombre", f"%{tokens_nombre[0]}%").limit(1).execute()
            if res_doc.data:
                doc_data = res_doc.data[0]
                centro_medico = doc_data.get("centro_medico") or centro_medico
                medico_nombre = doc_data.get("nombre") or medico_nombre
                doc_whatsapp = doc_data.get("telefono") or doc_data.get("whatsapp") or ""

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Paciente: {nombre_paciente} | Cédula: {cedula_paciente} | ARS: {ars_paciente} ({plan_ars}) | Médico: {medico_nombre} | Centro: {centro_medico} | Motivo: {motivo_consulta}",
            "estado": "pendiente_aprobacion",
            "doctor_whatsapp_jid": normalizar_jid(doc_whatsapp) if doc_whatsapp else None,
            "whatsapp_status": "pendiente",
            "costo_consulta": costo_consulta,
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        copia_notif = ""
        if cita_creada.get("id"):
            try:
                res_despacho = despachar_notificacion_doctor(cita_creada["id"])
                copia_notif = res_despacho.get("mensaje_doctor_texto", "")
            except Exception as err_notif:
                logger.error(f"⚠️ Error al despachar notificación: {err_notif}")

        mensaje_final = (
            f"Tu cita ha sido agendada exitosamente. Estamos enviando tu solicitud de cita al {medico_nombre}. Tan pronto el doctor confirme recibirás una notificación.\n\n"
            f"El siguiente mensaje le fue enviado al {medico_nombre}:\n\n"
            f"\"{copia_notif}\""
        )

        return json.dumps({
            "status": "exitoso",
            "mensaje_formateado_final": mensaje_final,
            "cita_id": cita_creada.get("id")
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Error en agendar_cita_medica: {e}")
        return json.dumps({"error": str(e)})

# ==========================================
# SYSTEM PROMPT - REGLA CERO ALUCINACIONES GEOGRÁFICAS
# ==========================================

SYSTEM_PROMPT_GEMA = f"""
Eres Gema, la asistente inteligente para citas médicas de VitalMi en República Dominicana.

### 📍 FORMATO DE PRESENTACIÓN Y REGLAS DE RESPUESTA:
1. Cuando invoques la herramienta `consultar_directorio_inteligente`:
   - Si `total_exacto` es MAYOR a 0:
     Presenta los resultados con: "Aquí tienes los [especialistas] disponibles en [Ubicación]:"
   - Si `total_exacto` es IGUAL a 0:
     Responde ÚNICAMENTE: "No encontré [especialistas] registrados en [Ubicación] en nuestro directorio. ¿Te gustaría buscar en otro sector o provincia?"
     *(NUNCA muestres médicos de Santo Domingo o de otra ciudad si no coinciden exactamente con la búsqueda).*

2. ESTRUCTURA ESTRICTA PARA CADA MÉDICO ENCONTRADO:
1. *[Nombre del Médico]*
 - Especialidad: [Especialidad/Subespecialidad]
 - Centro Médico: [Centro Médico]
 - Dirección: [Dirección exacta de la base de datos]
 - Teléfono: [Teléfono]
 - WhatsApp: [WhatsApp o 'No disponible']

### 📍 FLUJO CONVERSACIONAL PASO A PASO:
1. **PASO 1 (Solicitud sin ubicación):** Pregunta por la ciudad/sector si el usuario solo pide la especialidad.
2. **PASO 2 (Ubicación especificada):** Invoca `consultar_directorio_inteligente` y muestra los resultados siguiendo las reglas arriba indicadas.
3. **PASO 3 (Selección de médico):** Pregunta la fecha y tanda deseada.
4. **PASO 4 (Tarjeta de revisión):** Muestra el resumen y solicita confirmación ("¿Está todo bien con estos datos?").
5. **PASO 5 (Confirmación y envío):** Ejecuta `agendar_cita_medica` y entrega el mensaje final con la copia exacta enviada al médico.
"""

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    jid_normalizado = normalizar_jid(numero_usuario)
    paciente = registrar_o_actualizar_paciente(jid_normalizado, nombre_usuario)
    
    nombre_raw = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else nombre_usuario
    nombre_contacto = extraer_primer_nombre_valido(nombre_raw)

    guardar_mensaje_supabase(jid_normalizado, "user", mensaje_usuario)
    historial_raw = obtener_historial_supabase(jid_normalizado, limite=10)
    historial_limpio = [{"role": m["rol"] if "rol" in m else m["role"], "content": m["contenido"] if "contenido" in m else m["content"]} for m in historial_raw]

    ahora_rd = datetime.now(TZ_RD)
    contexto_temporal = f"\nHoy es {ahora_rd.strftime('%Y-%m-%d %H:%M:%S')} AST en República Dominicana."
    contexto_paciente = f"\nUSUARIO EN CHAT: '{nombre_contacto}' | WhatsApp: {jid_normalizado}."
    
    system_prompt = SYSTEM_PROMPT_GEMA + contexto_temporal + contexto_paciente

    tools = [
        {
            "type": "function",
            "function": {
                "name": "consultar_directorio_inteligente",
                "description": "Busca especialistas en el directorio médico de la ubicación exacta.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "especialidad": {"type": "string"},
                        "ubicacion": {"type": "string"},
                        "centro_medico": {"type": "string"},
                        "nombre_medico": {"type": "string"}
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

                if name == "consultar_directorio_inteligente":
                    args["mensaje_raw"] = mensaje_usuario
                    res_tool = consultar_directorio_inteligente(**args)
                elif name == "agendar_cita_medica":
                    args["telefono_jid"] = jid_normalizado
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

        guardar_mensaje_supabase(jid_normalizado, "assistant", respuesta_texto)
        return respuesta_texto

    except Exception as e:
        logger.error(f"❌ Error en gema_brain: {e}")
        return "Tuve un inconveniente técnico procesando tu solicitud. Por favor indícame la especialidad o doctor que buscas."

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)