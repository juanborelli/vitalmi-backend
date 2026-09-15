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

# Importar el nuevo esquema estricto (con fallback por seguridad)
try:
    from app.schemas.extraction import ExtraccionIntencion
except ImportError:
    from pydantic import BaseModel, Field
    class ExtraccionIntencion(BaseModel):
        intencion_usuario: str = Field(default="informacion")
        especialidad: Optional[str] = Field(default=None)
        ubicacion_provincia: Optional[str] = Field(default=None)
        aseguradora: Optional[str] = Field(default=None)
        tipo_entidad: Optional[str] = Field(default=None)
        nombre_medico: Optional[str] = Field(default=None)

# Importar funciones de Evolution Service con protección fallback
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
    return texto.strip().lower()

def extraer_primer_nombre_valido(nombre_raw: str) -> str:
    if not nombre_raw:
        return ""
    palabras = [p.capitalize() for p in nombre_raw.split() if len(p) > 2 and p.lower() not in ["del", "las", "los", "san", "santa", "usuario", "whatsapp"]]
    return palabras[0] if palabras else ""

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
    texto_clean = remover_tildes(str(texto_fecha))

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

def obtener_o_registrar_paciente_por_whatsapp(telefono_jid: str, nombre_push: str = "") -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return {}

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
        datos_nuevo = {
            "telefono_jid": jid_normalizado, 
            "nombre": nombre_inicial, 
            "perfil_completo": False,
            "created_at": obtener_hora_rd_iso()
        }
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
        logger.error(f"❌ Error identificando/registrando paciente por WhatsApp: {e}")
        return {}

def obtener_historial_supabase(telefono_jid: str, limite: int = 6) -> List[Dict[str, str]]:
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
# EXTRACCIÓN ESTRUCTURADA (PYDANTIC + OPENAI)
# ==========================================

async def extraer_parametros_async(mensaje_usuario: str, client: AsyncOpenAI) -> ExtraccionIntencion:
    try:
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": "Eres un extractor de datos médicos experto. Analiza el mensaje del usuario y extrae los parámetros solicitados basándote estrictamente en el esquema proporcionado. Si un dato no se menciona, asume None/null. No inventes."
                },
                {"role": "user", "content": mensaje_usuario}
            ],
            response_format=ExtraccionIntencion,
        )
        return response.choices[0].message.parsed
    except Exception as e:
        logger.error(f"⚠️ Error en extracción estructurada: {e}")
        return ExtraccionIntencion(intencion_usuario="informacion")

# ==========================================
# MOTOR HÍBRIDO: BÚSQUEDA VECTORIAL Y RPC (`buscar_prestadores_gema`)
# ==========================================

async def buscar_directorio_semantico_rpc(
    consulta_texto: str, 
    limite: int = 6, 
    filtro_aseguradora: Optional[str] = None, 
    filtro_provincia: Optional[str] = None, 
    filtro_tipo: Optional[str] = None
) -> str:
    supabase = obtener_cliente_supabase()
    client = obtener_cliente_openai()
    
    if not supabase or not client:
        return json.dumps({"error": "Sin conexión a base de datos o API de OpenAI"})

    try:
        logger.info(f"🧠 BÚSQUEDA HÍBRIDA GEMA (RPC): '{consulta_texto}' | Aseguradora: {filtro_aseguradora} | Provincia: {filtro_provincia} | Límite: {limite}")

        emb_response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=consulta_texto
        )
        query_vector = emb_response.data[0].embedding

        res = supabase.rpc("buscar_prestadores_gema", {
            "busqueda_texto": consulta_texto,
            "query_embedding": query_vector,
            "filtro_aseguradora": filtro_aseguradora,
            "filtro_provincia": filtro_provincia,
            "filtro_tipo": filtro_tipo,
            "limite": limite
        }).execute()

        resultados = res.data or []

        prestadores_procesados = []
        for r in resultados:
            item = dict(r)
            item['tipo_prestador'] = item.get('tipo_prestador') or 'PRESTADOR'
            
            # Garantizar especialidad 100% oficial y segura
            esp_oficial = item.get('especialidad_medico') or item.get('especialidad')
            esp_cons = item.get('especialidades_consolidadas')
            
            if esp_oficial:
                item['especialidad_final'] = esp_oficial
            elif isinstance(esp_cons, list) and esp_cons:
                item['especialidad_final'] = ", ".join(esp_cons)
            else:
                item['especialidad_final'] = 'General / Sin especificar'
                
            item['telefono_final'] = item.get('telefono_institucional') or 'No disponible'
            item['whatsapp_final'] = item.get('whatsapp') or item.get('telefono_institucional') or 'No disponible'
            prestadores_procesados.append(item)

        return json.dumps({
            "total_encontrados": len(prestadores_procesados),
            "prestadores": prestadores_procesados
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Error en búsqueda RPC de Gema: {e}")
        return json.dumps({"error": str(e), "total_encontrados": 0, "prestadores": []})

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
        res_doc = supabase.table("vitalmi_directorio_master").select("telefono_institucional, whatsapp").ilike("nombre", f"%{medico_nombre.split()[0]}%").limit(1).execute()
        if res_doc.data:
            sec_phone = res_doc.data[0].get("whatsapp") or res_doc.data[0].get("telefono_institucional")
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
                "mensaje": f"Para poder agendar y confirmar formalmente tu cita médica con el doctor, necesitamos que completes tus datos en nuestro formulario oficial de registro: {URL_FORM_OFICIAL}\n\nUna vez completado el formulario, confírmame por aquí y con gusto agendamos tu cita."
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
                doc_whatsapp = doc_data.get("whatsapp") or doc_data.get("telefono_institucional") or ""

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
# SYSTEM PROMPT PERFECCIONADO
# ==========================================

SYSTEM_PROMPT_GEMA = f"""
Eres Gema, la asistente inteligente para citas médicas y servicios de salud de VitalMi en República Dominicana.

### 👤 RECONOCIMIENTO Y UBICACIÓN DEL USUARIO:
- Cuentas con la identidad y ubicación guardada del usuario en el contexto (`Nombre identificado` y `Ubicación Habitual`).
- Si el usuario pregunta quién le escribe o si lo conoces, salúdalo personalmente por su nombre.
- **Uso de Ubicación Habitual:** Si el usuario busca un servicio general sin especificar ciudad (ej: "necesito una farmacia", "busco un cardiólogo"), UTILIZA su `Ubicación Habitual` en la búsqueda (por ejemplo, pasándola en `filtro_provincia`).

### ⚡ REGLA DE AGILIDAD EN BÚSQUEDA (CRÍTICO):
1. Cuando el usuario solicite un servicio, DEBES utilizar los filtros extraídos y provistos en el bloque 'EXTRACCIÓN ESTRUCTURADA'.
2. DEBES MOSTRAR INMEDIATAMENTE las opciones disponibles ejecutando `buscar_directorio_semantico_rpc`.
3. NO le pidas hora, motivo ni confirmación de tercero ANTES de mostrar los médicos. Muestra la lista primero.
4. NUNCA inventes nombres, teléfonos ni direcciones. Invoca obligatoriamente la herramienta.

### 📊 REGLA DE LÍMITE DINÁMICO DE BÚSQUEDA (CRÍTICO):
- **Búsquedas Puntuales:** Si el usuario busca un prestador específico (ej: "necesito un cardiólogo", "busco un pediatra"), pasa un `limite` de **6** para no saturar la respuesta.
- **Búsquedas Masivas / Conteo:** Si el usuario pregunta explícitamente por cantidades, totales o listados generales (ej: "¿Cuántas farmacias hay?", "Dame la lista de todos los centros médicos"), DEBES pasar un `limite` alto (ej: **30 o 50**) para que la base de datos devuelva el universo completo de registros.
- **Especialidad 100% Segura:** Al presentar los resultados al usuario, muestra siempre la especialidad oficial consolidada de la base de datos de forma clara y directa.

### 🔄 REGLA DE FLEXIBILIDAD Y ALTERNATIVAS:
- Si la búsqueda con filtros estrictos (ej. especialidad + ARS específica) arroja **0 resultados**, no te limites a decir que no hay nada. 
- Informa al usuario con honestidad sobre lo que *sí* está disponible (por ejemplo, si el médico está registrado pero con otra ARS o especialidad cercana) para guiarlo de forma útil.

### 👥 MANEJO DE CITAS PARA TERCEROS:
- Si el usuario indica que la cita es para otra persona (ej. "para mi madre", "un familiar"), asegúrate de procesar el agendamiento indicando `es_para_tercero: true`.
"""

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    jid_normalizado = normalizar_jid(numero_usuario)
    paciente = obtener_o_registrar_paciente_por_whatsapp(jid_normalizado, nombre_usuario)
    
    nombre_db = paciente.get("nombre") or nombre_usuario
    nombre_contacto = extraer_primer_nombre_valido(nombre_db)

    provincia_user = paciente.get("provincia") or ""
    municipio_user = paciente.get("municipio") or paciente.get("sector") or ""
    
    ubicacion_str = ""
    if provincia_user or municipio_user:
        ubicacion_str = f"{municipio_user}, {provincia_user}".strip(", ")
    else:
        ubicacion_str = "San Cristóbal, República Dominicana"

    guardar_mensaje_supabase(jid_normalizado, "user", mensaje_usuario)
    historial_raw = obtener_historial_supabase(jid_normalizado, limite=6)
    historial_limpio = [{"role": m["rol"] if "rol" in m else m["role"], "content": m["contenido"] if "contenido" in m else m["content"]} for m in historial_raw]

    # === 1. EJECUCIÓN DE EXTRACCIÓN ESTRUCTURADA ===
    datos_extraidos = await extraer_parametros_async(mensaje_usuario, client)
    logger.info(f"🧠 Datos interpretados (Pydantic): {datos_extraidos.model_dump()}")

    # === 2. MAPEO Y CONSTRUCCIÓN DE ARGUMENTOS SUGERIDOS ===
    argumentos_sugeridos = {}
    if datos_extraidos.especialidad or datos_extraidos.nombre_medico:
        argumentos_sugeridos["consulta_texto"] = datos_extraidos.especialidad or datos_extraidos.nombre_medico
    if datos_extraidos.aseguradora:
        argumentos_sugeridos["filtro_aseguradora"] = datos_extraidos.aseguradora
    if datos_extraidos.ubicacion_provincia:
        argumentos_sugeridos["filtro_provincia"] = datos_extraidos.ubicacion_provincia
    if datos_extraidos.tipo_entidad:
        argumentos_sugeridos["filtro_tipo"] = datos_extraidos.tipo_entidad

    # === 3. CONSTRUCCIÓN DEL CONTEXTO FINAL ===
    ahora_rd = datetime.now(TZ_RD)
    contexto_temporal = f"\n\n🕒 Hoy es {ahora_rd.strftime('%Y-%m-%d %H:%M:%S')} AST."
    contexto_paciente = f"\n👤 USUARIO: Nombre='{nombre_contacto or 'Usuario'}' | WhatsApp={jid_normalizado} | Ubicación='{ubicacion_str}'."
    
    contexto_extraccion = (
        f"\n\n🔍 EXTRACCIÓN ESTRUCTURADA (OBLIGATORIA):\n"
        f"El sistema ha pre-analizado los requerimientos. Al llamar a la herramienta `buscar_directorio_semantico_rpc`, "
        f"utiliza EXCLUSIVAMENTE estos argumentos exactos (ignora llaves que no estén aquí):\n{json.dumps(argumentos_sugeridos, ensure_ascii=False)}"
    )

    system_prompt = SYSTEM_PROMPT_GEMA + contexto_temporal + contexto_paciente + contexto_extraccion

    tools = [
        {
            "type": "function",
            "function": {
                "name": "buscar_directorio_semantico_rpc",
                "description": "Busca prestadores de salud usando búsqueda híbrida en Supabase.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "consulta_texto": {"type": "string"},
                        "filtro_aseguradora": {"type": "string"},
                        "filtro_provincia": {"type": "string"},
                        "filtro_tipo": {"type": "string"},
                        "limite": {"type": "integer"}
                    }, 
                    "required": ["consulta_texto"]
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

                if name == "buscar_directorio_semantico_rpc":
                    # Blindaje crítico: Si la IA omitió consulta_texto, usar tipo_entidad o provincia por defecto
                    if not args.get("consulta_texto"):
                        args["consulta_texto"] = args.get("filtro_tipo") or args.get("filtro_provincia") or "medico"
                    
                    res_tool = await buscar_directorio_semantico_rpc(**args)
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
                max_tokens=650
            )
            
            respuesta_texto = second_response.choices[0].message.content.strip()
        else:
            respuesta_texto = response_message.content.strip()

        guardar_mensaje_supabase(jid_normalizado, "assistant", respuesta_texto)
        return respuesta_texto

    except Exception as e:
        logger.error(f"❌ Error en gema_brain: {e}")
        return "Tuve un inconveniente técnico procesando tu solicitud. Por favor indícame la especialidad o servicio médico que buscas."

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)