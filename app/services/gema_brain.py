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
            dias_diferencia = idx_target - ahora_rd.weekday()
            if dias_diferencia <= 0:
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
# DIRECTORIO MASTER - FILTRADO STRICTO POR PROVINCIA Y ESPECIALIDAD
# ==========================================

def consultar_directorio_inteligente(
    especialidad: str = "", 
    ubicacion: str = "", 
    centro_medico: str = "",
    nombre_medico: str = ""
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"total_exacto": 0, "medicos_muestra": []})

    try:
        tok_esp = remover_tildes(especialidad).lower().strip()
        for r in ["cardio", "pediat", "urol", "ginec", "derma", "oftalmo", "ortop", "odont", "interna"]:
            if r in tok_esp:
                tok_esp = r
                break

        tok_ubi = remover_tildes(ubicacion).lower().strip()
        tok_cent = remover_tildes(centro_medico).lower().strip()
        tok_nom = remover_tildes(nombre_medico).lower().strip()

        # Consulta inicial a Supabase filtrando por especialidad
        q = supabase.table("vitalmi_directorio_master").select("*")

        if tok_esp:
            q = q.ilike("especialidad", f"%{tok_esp}%")

        res = q.limit(50).execute()
        registros = res.data or []

        # Filtrado ESTRICTO en memoria de Python por Ubicación/Provincia
        if registros and (tok_ubi or tok_cent or tok_nom):
            filtrados = []
            for r in registros:
                prov_str = remover_tildes(r.get('provincia', '')).lower()
                muni_str = remover_tildes(r.get('municipio', '')).lower()
                dir_str = remover_tildes(r.get('direccion', '')).lower()
                cent_str = remover_tildes(r.get('centro_medico', '')).lower()
                nom_str = remover_tildes(r.get('nombre', '')).lower()

                texto_geografico = f"{prov_str} {muni_str} {dir_str} {cent_str}"

                # Exigir que los tokens de la provincia solicitada estén presentes en el registro
                match_ubi = True
                if tok_ubi:
                    tokens_ubi = [t for t in tok_ubi.split() if len(t) > 2 and t not in ["para", "en", "el", "la", "los", "las"]]
                    if tokens_ubi:
                        match_ubi = all(t in texto_geografico for t in tokens_ubi)

                match_cent = not tok_cent or tok_cent in cent_str or tok_cent in dir_str
                match_nom = not tok_nom or tok_nom in nom_str

                if match_ubi and match_cent and match_nom:
                    filtrados.append(r)
            
            medicos_finales = filtrados[:5]
        else:
            medicos_finales = registros[:5] if not tok_ubi else []

        return json.dumps({
            "total_exacto": len(medicos_finales),
            "medicos_muestra": medicos_finales
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Error en consultar_directorio_inteligente: {e}")
        return json.dumps({"total_exacto": 0, "medicos_muestra": []}, ensure_ascii=False)

# ==========================================
# NOTIFICACIÓN Y AGENDAMIENTO DE CITAS
# ==========================================

def agendar_cita_medica(
    telefono_jid: str, 
    medico_nombre: str, 
    fecha_cita: str = "Mañana", 
    tanda: str = "Mañana", 
    es_para_tercero: bool = False,
    telefono_tercero: str = "",
    nombre_menor_paciente: str = "",
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
        nombre_tutor = paciente.get("nombre", "Paciente Titular")
        
        if nombre_menor_paciente:
            nombre_paciente_final = f"{nombre_menor_paciente.strip()} (Tutor: {nombre_tutor})"
        else:
            nombre_paciente_final = nombre_tutor

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
        if "sabado" in tanda_clean or "sábado" in tanda_clean or (fecha_dt and fecha_dt.weekday() == 5):
            tanda_texto = "Sábados (9:00 AM – 2:00 PM)"
        elif "tarde" in tanda_clean:
            tanda_texto = "Tarde (3:00 PM – 6:00 PM)"
        else:
            tanda_texto = "Mañana (9:00 AM – 12:00 PM)"

        centro_medico = "Consultorio Privado Autorizado"
        especialidad_medico = "Especialista Clínico"
        costo_consulta = 2500.00
        doc_whatsapp = ""

        tokens_nombre = [t for t in remover_tildes(medico_nombre).split() if len(t) > 3]
        if tokens_nombre:
            res_doc = supabase.table("vitalmi_directorio_master").select("*").ilike("nombre", f"%{tokens_nombre[0]}%").limit(1).execute()
            if res_doc.data:
                doc_data = res_doc.data[0]
                centro_medico = doc_data.get("centro_medico") or centro_medico
                medico_nombre = doc_data.get("nombre") or medico_nombre
                especialidad_medico = doc_data.get("especialidad") or doc_data.get("especialidad_medico") or especialidad_medico
                doc_whatsapp = doc_data.get("telefono") or doc_data.get("whatsapp") or ""

        # CONSTRUCCIÓN GARANTIZADA DE LA NOTIFICACIÓN PARA EL MÉDICO
        motivo_completo = f"Paciente: {nombre_paciente_final} | Cédula Tutor: {cedula_paciente} | ARS: {ars_paciente} ({plan_ars}) | Médico: {medico_nombre} | Centro: {centro_medico} | Motivo: {motivo_consulta}"

        mensaje_doctor_texto = (
            f"Estimado(a) {medico_nombre},\n\n"
            "Soy Gema, la asistente inteligente para citas médicas de VitalMi.\n\n"
            f"📝 *NUEVA SOLICITUD DE CITA:*\n"
            f"• *Paciente:* {nombre_paciente_final}\n"
            f"• *ARS:* {ars_paciente} ({plan_ars})\n"
            f"• *Fecha y Horario:* {fecha_formateada} ({tanda_texto})\n"
            f"• *Centro Médico:* {centro_medico}\n"
            f"• *Costo Estimado:* RD$ {costo_consulta:,.2f}\n\n"
            "Por favor responda a este mensaje con:\n"
            "✅ *CONFIRMAR* - Para aceptar la cita.\n"
            "❌ *RECHAZAR* - Para indicar que no hay disponibilidad."
        )

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": motivo_completo,
            "estado": "pendiente_aprobacion",
            "doctor_whatsapp_jid": normalizar_jid(doc_whatsapp) if doc_whatsapp else None,
            "whatsapp_status": "pendiente",
            "costo_consulta": costo_consulta,
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        # Intentar envío por WhatsApp si existe JID
        if cita_creada.get("id") and doc_whatsapp:
            try:
                doc_jid = normalizar_jid(doc_whatsapp)
                enviar_mensaje_whatsapp(doc_jid, mensaje_doctor_texto)
                supabase.table("citas").update({"whatsapp_status": "enviado"}).eq("id", cita_creada["id"]).execute()
            except Exception as err_notif:
                logger.error(f"⚠️ Error al enviar WhatsApp al doctor: {err_notif}")

        mensaje_paciente = (
            f"Tu cita ha sido agendada exitosamente. Estamos enviando tu solicitud de cita al {medico_nombre}. Tan pronto el doctor confirme, recibirás una notificación.\n\n"
            f"El siguiente mensaje le fue enviado al {medico_nombre}:\n\n"
            f"\"{mensaje_doctor_texto}\""
        )

        return json.dumps({
            "status": "exitoso",
            "mensaje_formateado_final": mensaje_paciente,
            "cita_id": cita_creada.get("id")
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Error en agendar_cita_medica: {e}")
        return json.dumps({"error": str(e)})

# ==========================================
# SYSTEM PROMPT CON REGLA CERO-ALUCINACIONES
# ==========================================

SYSTEM_PROMPT_GEMA = f"""
Eres Gema, la asistente inteligente para citas médicas de VitalMi en República Dominicana.
Debes seguir ESTRICTAMENTE el siguiente flujo conversacional en cada paso:

### 📍 FLUJO CONVERSACIONAL GUIADO PASO A PASO:

1. **PASO 1 (SOLICITUD INICIAL GENÉRICA SIN UBICACIÓN):**
   - Si el usuario dice que necesita un especialista pero NO INDICA ciudad ni centro médico (ej. "Gema, necesito un urólogo"):
     * NO INVOQUES LA HERRAMIENTA `consultar_directorio_inteligente`.
     * Responde: "Hola [Nombre], ¿puedes decirme para dónde necesitas el [especialista]?"

2. **PASO 2 (RECEPCIÓN DE UBICACIÓN Y PRESENTACIÓN):**
   - Cuando el usuario indique la provincia, municipio o centro (ej. "Para San Cristóbal"):
     * Invoca `consultar_directorio_inteligente` pasando la provincia/ubicación.
     * **REGLA DE ORO CERO ALUCINACIONES:** Muestra ÚNICAMENTE los médicos exactos que devuelva la herramienta. NUNCA presentes a un médico de Santiago o Santo Domingo como si fuera de San Cristóbal.
     * Si la herramienta devuelve 0 resultados, responde: "No encontré [especialistas] registrados en [Ubicación] en nuestra base de datos. ¿Te gustaría intentar en otra provincia o centro médico?"

3. **PASO 3 (RESPUESTA DE AGRADECIMIENTO TRAS LA LISTA):**
   - Si el usuario dice "ok, gracias" tras ver los médicos:
     * Responde: "A tu orden [Nombre]. Si necesitas hacer una cita con uno de esos [especialistas], solo déjame saber."

4. **PASO 4 (SELECCIÓN DE DOCTOR):**
   - Cuando el usuario indique con cuál médico quiere agendar (ej. "Con el doctor del Rosario"):
     * Responde: "¿Puedes indicarme para cuándo la quieres, y si es para la tarde, la mañana, o sábado?"

5. **PASO 5 (DETALLES PARA REVISIÓN):**
   - Cuando el usuario proporcione la fecha y tanda (ej. "para este viernes en la mañana"):
     * Muestra la tarjeta de revisión: "Bien [Nombre], aquí tienes los detalles de la cita para tu revisión:\n\n• Médico: [Doctor]\n• Centro: [Centro]\n• Fecha: [Fecha formateada con día de la semana]\n• Tanda: [Tarde/Mañana]\n\n¿Está todo bien con estos datos?"

6. **PASO 6 (CONFIRMACIÓN Y ENVÍO):**
   - Cuando el usuario confirme ("ok. está todo bien" / "sí"):
     * Ejecuta `agendar_cita_medica`.
     * Entrega la respuesta final retornada que contiene la confirmación y la COPIA COMPLETA DEL MENSAJE AL DOCTOR (nunca vacía).

7. **PASO 7 (DESPEDIDA Y AGRADECIMIENTOS FINALES):**
   - Si el usuario dice "Gracias Gema":
     * Responde: "A tu orden [Nombre]. En lo que recibes la confirmación de tu cita, ¿hay algo más en lo que pueda ayudarte?"
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
                "description": "Busca especialistas en el directorio una vez definida la ubicación o centro médico.",
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
                        "nombre_menor_paciente": {"type": "string"},
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