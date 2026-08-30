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
        telefono_solo_numeros = re.sub(r"\D", "", telefono_jid)
        ultimos_10_digitos = telefono_solo_numeros[-10:] if len(telefono_solo_numeros) >= 10 else telefono_solo_numeros
        
        nombre_guardar = nombre_push.strip() if (nombre_push and nombre_push.strip()) else "Usuario WhatsApp"
        
        res = supabase.table("pacientes").select("*").eq("telefono_jid", jid_normalizado).execute()
        
        if not res.data and ultimos_10_digitos:
            res = supabase.table("pacientes").select("*").ilike("telefono_jid", f"%{ultimos_10_digitos}%").execute()

        if res.data and len(res.data) > 0:
            paciente_existente = res.data[0]
            if paciente_existente.get("telefono_jid") != jid_normalizado:
                supabase.table("pacientes").update({
                    "telefono_jid": jid_normalizado,
                    "updated_at": obtener_hora_rd_iso()
                }).eq("id", paciente_existente["id"]).execute()
                paciente_existente["telefono_jid"] = jid_normalizado
            
            return paciente_existente

        datos_nuevo = {
            "telefono_jid": jid_normalizado, 
            "nombre": nombre_guardar, 
            "perfil_completo": False,
            "created_at": obtener_hora_rd_iso()
        }
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
        print(f"❌ Error buscando o registrando paciente: {e}")
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
        registros = response.data[::-1] if response.data else []
        return registros
    except Exception as e:
        return []

def guardar_mensaje_supabase(telefono_jid: str, rol: str, contenido: str, tipo_mensaje: str = "texto"):
    supabase = obtener_cliente_supabase()
    if not supabase:
        return

    try:
        jid_norm = normalizar_jid(telefono_jid)
        data = {
            "telefono_jid": jid_norm,
            "rol": rol,
            "contenido": contenido,
            "tipo_mensaje": tipo_mensaje,
            "created_at": obtener_hora_rd_iso()
        }
        supabase.table("historial_chats").insert(data).execute()
    except Exception as e:
        print(f"❌ Error guardando mensaje: {e}")

# ==========================================
# DIRECTORIO MASTER - ALGORITMO DE BÚSQUEDA AISLADO
# ==========================================

def consultar_directorio_inteligente(
    provincia: str = "", 
    municipio: str = "",
    sector: str = "",
    especialidad: str = "", 
    nombre_medico: str = "", 
    centro_medico_preferido: str = "",
    mensaje_raw: str = ""
) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return json.dumps({"total_exacto": 0, "medicos_muestra": []})

    try:
        texto_msg = remover_tildes(mensaje_raw).lower()
        texto_medico = remover_tildes(nombre_medico).lower()
        texto_centro = remover_tildes(centro_medico_preferido).lower()

        # Detección de especialidad por tokens
        token_especialidad = ""
        especialidades_clave = [
            ("cardio", "Cardiología"), ("pediat", "Pediatría"), ("ginec", "Ginecología"), 
            ("urol", "Urología"), ("derma", "Dermatología"), ("oftalmo", "Oftalmología"), 
            ("ortop", "Ortopedia"), ("odont", "Odontología"), ("psiquiat", "Psiquiatría"), 
            ("neurol", "Neurología"), ("interna", "Medicina Interna")
        ]
        for key, _ in especialidades_clave:
            if key in remover_tildes(especialidad).lower() or key in texto_msg:
                token_especialidad = key
                break

        # EXTRAER CIUDAD SOLO SI CONSTA EN EL MENSAJE ACTUAL
        ciudades_conocidas = [
            "santiago", "san cristobal", "san pedro", "san juan", "samana", 
            "la romana", "bani", "santo domingo", "higuey", "puerto plata", "barahona", "azua"
        ]
        ciudad_mensaje_actual = ""
        for c in ciudades_conocidas:
            if c in texto_msg:
                ciudad_mensaje_actual = c
                break

        # CASO 1: Búsqueda por Nombre de Médico (sin restringir por provincia previa)
        tokens_nombre = [t for t in re.findall(r'\b\w{3,}\b', texto_medico or texto_msg) if t not in ["doctor", "doctora", "dra", "dr", "clinica", "san", "necesito", "cita", "con", "este"]]
        if tokens_nombre and ("dr" in texto_msg or "doctor" in texto_msg or nombre_medico):
            q_name = supabase.table("vitalmi_directorio_master").select("*")
            for tok in tokens_nombre[:2]:
                q_name = q_name.ilike("nombre", f"%{tok}%")
            
            if ciudad_mensaje_actual:
                q_name = q_name.or_(f"provincia.ilike.%{ciudad_mensaje_actual}%,municipio.ilike.%{ciudad_mensaje_actual}%,direccion.ilike.%{ciudad_mensaje_actual}%")

            res_name = q_name.limit(5).execute()
            if res_name.data and len(res_name.data) > 0:
                return json.dumps({
                    "nivel_busqueda": "nombre_exacto",
                    "total_exacto": len(res_name.data),
                    "medicos_muestra": res_name.data
                }, ensure_ascii=False)

        # CASO 2: Búsqueda por Centro Médico (ej. SEMECO, Betancourt)
        palabras_centro = ["semeco", "cedano", "pina", "bethancur", "betancourt", "abel gonzalez", "homs"]
        target_centro = texto_centro or texto_msg
        centro_detectado = next((pc for pc in palabras_centro if pc in target_centro), "")

        if centro_detectado:
            q_cent = supabase.table("vitalmi_directorio_master").select("*")
            if token_especialidad:
                q_cent = q_cent.or_(f"especialidad.ilike.%{token_especialidad}%,especialidad_medico.ilike.%{token_especialidad}%")
            q_cent = q_cent.ilike("centro_medico", f"%{centro_detectado}%")
            res_cent = q_cent.limit(5).execute()
            if res_cent.data and len(res_cent.data) > 0:
                return json.dumps({
                    "nivel_busqueda": "centro_medico_exacto",
                    "total_exacto": len(res_cent.data),
                    "medicos_muestra": res_cent.data
                }, ensure_ascii=False)

        # CASO 3: Búsqueda por Especialidad y Ubicación
        q_geo = supabase.table("vitalmi_directorio_master").select("*")

        if token_especialidad:
            q_geo = q_geo.or_(f"especialidad.ilike.%{token_especialidad}%,especialidad_medico.ilike.%{token_especialidad}%")

        lugar_final = ciudad_mensaje_actual or remover_tildes(provincia or municipio or sector).strip().lower()

        if lugar_final:
            q_geo = q_geo.or_(f"provincia.ilike.%{lugar_final}%,municipio.ilike.%{lugar_final}%,direccion.ilike.%{lugar_final}%,centro_medico.ilike.%{lugar_final}%")

        res_geo = q_geo.limit(5).execute()
        medicos = res_geo.data or []

        return json.dumps({
            "nivel_busqueda": "coincidencia_exitosa" if medicos else "sin_resultados",
            "lugar_solicitado": lugar_final or "General",
            "total_exacto": len(medicos),
            "medicos_muestra": medicos
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Error en consultar_directorio_inteligente: {e}")
        return json.dumps({"nivel_busqueda": "error", "total_exacto": 0, "medicos_muestra": []}, ensure_ascii=False)

def despachar_notificacion_doctor(cita_id: str) -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return {"status": "error", "mensaje": "Sin conexión a base de datos"}

    res_cita = supabase.table("citas").select("*").eq("id", cita_id).execute()
    if not res_cita.data:
        return {"status": "error", "mensaje": "Cita no encontrada"}

    cita = res_cita.data[0]
    doc_jid = cita.get("doctor_whatsapp_jid")
    
    motivo_raw = cita.get("motivo_consulta", "")
    medico_nombre = ""
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
            whatsapp_valido = False

    if not whatsapp_valido:
        logger.warning(f"⚠️ WhatsApp del médico ({doc_jid}) no activo. Conmutando a secretaría...")
        if medico_nombre:
            res_doc = supabase.table("vitalmi_directorio_master").select("telefono, whatsapp, centro_medico").ilike("nombre", f"%{medico_nombre}%").limit(1).execute()
            if res_doc.data:
                sec_phone = res_doc.data[0].get("whatsapp") or res_doc.data[0].get("telefono")
                if sec_phone:
                    doc_jid = normalizar_jid(sec_phone)
                    logger.info(f"📍 Redirigido a WhatsApp de Secretaría: {doc_jid}")

    if not doc_jid:
        logger.error(f"❌ No se encontró número de WhatsApp válido para la cita #{cita_id}")
        supabase.table("citas").update({"whatsapp_status": "fallido_sin_numero"}).eq("id", cita_id).execute()
        return {"status": "fallido", "error": "Sin número de WhatsApp válido"}

    mensaje_doctor = (
        "🏥 *NUEVA SOLICITUD DE CITA - VITALMI*\n\n"
        f"📝 *Detalles de la Cita #{str(cita_id)[:8]}:*\n"
        f"• *Datos del Paciente:* {cita.get('motivo_consulta')}\n"
        f"• *Costo Estimado:* RD$ {cita.get('costo_consulta', 2500):,.2f}\n"
        f"• *Atención:* {cita.get('reglas_llegada')}\n\n"
        "Por favor responda a este mensaje con una de estas opciones:\n"
        "✅ *CONFIRMAR* - Para aceptar la cita en el horario solicitado.\n"
        "❌ *RECHAZAR* - Para indicar que no hay disponibilidad."
    )

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
        
        return {"status": "exitoso", "jid_destinatario": doc_jid, "message_id": msg_id}
    else:
        supabase.table("citas").update({"whatsapp_status": "fallido_envio"}).eq("id", cita_id).execute()
        return {"status": "fallido", "error": "Falló el envío de la API"}

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
        palabras_invalidas = ["chequeo", "rutina", "consulta", "general", "cita", "revision"]
        nombre_clean = remover_tildes(medico_nombre).lower()
        if any(w in nombre_clean for w in palabras_invalidas) and len(medico_nombre.split()) < 4:
            res_last = supabase.table("vitalmi_directorio_master").select("*").order("created_at", desc=True).limit(1).execute()
            if res_last.data:
                medico_nombre = res_last.data[0].get("nombre")

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
        metodo_pago = "Efectivo / Facturación en recepción"
        reglas_llegada = "Orden de llegada. La recepción abre 30 mins antes de la tanda."
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

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Paciente: {nombre_paciente_final} | Cédula Tutor: {cedula_paciente} | ARS: {ars_paciente} ({plan_ars}) | Médico: {medico_nombre} | Centro: {centro_medico} | Motivo: {motivo_consulta}",
            "estado": "pendiente_aprobacion",
            "doctor_whatsapp_jid": normalizar_jid(doc_whatsapp) if doc_whatsapp else None,
            "whatsapp_status": "pendiente",
            "costo_consulta": costo_consulta,
            "metodo_pago": metodo_pago,
            "reglas_llegada": reglas_llegada,
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

        if cita_creada.get("id"):
            try:
                despachar_notificacion_doctor(cita_creada["id"])
            except Exception as err_notif:
                logger.error(f"⚠️ Error al despachar notificación al doctor: {err_notif}")

        mensaje_final = (
            "📋 *SOLICITUD DE CITA REGISTRADA*\n\n"
            "👤 *DATOS DEL PACIENTE:*\n"
            f"• *Nombre:* {nombre_paciente_final}\n"
            f"• *Cédula Tutor:* {cedula_paciente}\n"
            f"• *ARS:* {ars_paciente} ({plan_ars})\n\n"
            "👨‍⚕️ *ESPECIALISTA Y CENTRO:*\n"
            f"• *Doctor:* {medico_nombre}\n"
            f"• *Especialidad:* {especialidad_medico}\n"
            f"• *Centro Médico:* {centro_medico}\n\n"
            "📅 *HORARIO Y LOGÍSTICA:*\n"
            f"• *Fecha:* {fecha_formateada}\n"
            f"• *Tanda:* {tanda_texto}\n"
            f"• *Costo Estimado:* RD$ {costo_consulta:,.2f} ({metodo_pago})\n"
            f"• *Atención:* {reglas_llegada}\n\n"
            "⏳ *ESTADO:* Solicitud enviada al doctor/secretaría. Te notificaremos por aquí tan pronto sea confirmada."
        )

        return json.dumps({
            "status": "exitoso",
            "mensaje_formateado_final": mensaje_final,
            "cita_id": cita_creada.get("id")
        }, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en agendar_cita_medica: {e}")
        return json.dumps({"error": str(e)})

SYSTEM_PROMPT_GEMA = f"""
Eres Gema, la asistente inteligente para citas médicas de VitalMi en República Dominicana.

### 📍 REGLAS DE BÚSQUEDA Y TRANSPARENCIA:
1. SIEMPRE utiliza `consultar_directorio_inteligente` para consultar especialistas.
2. NO arrastres provincias o ubicaciones del mensaje anterior si el usuario está preguntando por una nueva clínica o médico.
3. SI la herramienta retorna médicos, preséntalos de inmediato con su Nombre, Especialidad, Centro Médico y Teléfono.
4. SI la herramienta devuelve 0 resultados, responde de forma transparente: "No encontré médicos registrados para esa búsqueda específica. ¿Te gustaría intentar en otra zona o especialidad?"

### 📅 REGLA DE TARJETA DE CONFIRMACIÓN PREVIA:
Si el usuario especifica fecha y tanda para agendar, DEBES mostrar la tarjeta de resumen previo antes de registrar la cita:
"📌 *RESUMEN DE TU SOLICITUD DE CITA:*
• *Paciente:* [Nombre + Edad] — Tutor: [Nombre Usuario]
• *Especialista:* [Nombre Doctor]
• *Centro Médico:* [Centro Médico]
• *Fecha Solicitada:* [Fecha con día de semana correcto]
• *Tanda y Horario:* [Mañana (9:00 AM – 12:00 PM) / Tarde (3:00 PM – 6:00 PM) / Sábados (9:00 AM – 2:00 PM)]

Antes de enviar la solicitud al doctor, favor confirmarnos si los datos de la cita son correctos. ¿Son correctos?"
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
                "description": "Busca especialistas en el directorio por nombre, especialidad, centro médico o zona.",
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "especialidad": {"type": "string"},
                        "nombre_medico": {"type": "string"},
                        "provincia": {"type": "string"},
                        "municipio": {"type": "string"},
                        "sector": {"type": "string"},
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
        print(f"❌ Error en gema_brain: {e}")
        return "Tuve un inconveniente técnico procesando tu solicitud. Por favor indícame la especialidad o doctor que buscas."

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)