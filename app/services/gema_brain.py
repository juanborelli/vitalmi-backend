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
        fecha_calc = ahora_rd + timedelta(days=1)
        return fecha_calc.strftime("%Y-%m-%d")

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

# ==========================================
# MÓDULO DE RESOLUCIÓN GEOGRÁFICA (RD)
# ==========================================

def autodetectar_ubicacion(sector_usuario: str) -> Dict[str, str]:
    """
    Recibe un sector/barrio o municipio (ej: 'Piantini', 'Madre Vieja') y resuelve 
    automáticamente su Provincia, Municipio y Sector en Supabase.
    """
    supabase = obtener_cliente_supabase()
    if not supabase or not sector_usuario:
        return {}

    sector_limpio = sector_usuario.strip()

    # 1. Resolver mediante la Función RPC resolver_ubicacion_rd
    try:
        res_rpc = supabase.rpc("resolver_ubicacion_rd", {"texto_sector": sector_limpio}).execute()
        if res_rpc.data and len(res_rpc.data) > 0:
            data = res_rpc.data[0]
            logger.info(f"📍 Ubicación resuelta vía RPC: {data}")
            return {
                "provincia": data.get("provincia", ""),
                "municipio": data.get("municipio", ""),
                "sector": data.get("sector", sector_limpio)
            }
    except Exception as e:
        logger.warning(f"⚠️ Error o timeout en RPC resolver_ubicacion_rd: {e}")

    # 2. Fallback sobre la Vista Consolidada vista_geo_rd
    try:
        res_vista = (
            supabase.table("vista_geo_rd")
            .select("provincia, municipio, barrio")
            .ilike("busqueda_texto", f"%{remover_tildes(sector_limpio).lower()}%")
            .limit(1)
            .execute()
        )
        if res_vista.data and len(res_vista.data) > 0:
            data = res_vista.data[0]
            logger.info(f"📍 Ubicación resuelta vía vista_geo_rd: {data}")
            return {
                "provincia": data.get("provincia", ""),
                "municipio": data.get("municipio", ""),
                "sector": data.get("barrio", sector_limpio)
            }
    except Exception as e:
        logger.error(f"❌ Error consultando vista_geo_rd: {e}")

    return {"sector": sector_limpio}

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

        if not res.data and nombre_guardar not in ["Usuario WhatsApp", "Paciente", "Trancrédito", ""]:
            res = supabase.table("pacientes").select("*").ilike("nombre", nombre_guardar).execute()

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

def verificar_registro_tercero(telefono_tercero: str) -> str:
    supabase = obtener_cliente_supabase()
    if not supabase or not telefono_tercero:
        return json.dumps({"registrado": False, "mensaje": "Teléfono inválido o sin datos."})

    jid_tercero = normalizar_jid(telefono_tercero)

    try:
        res = supabase.table("pacientes").select("id, nombre, perfil_completo, provincia, ars").eq("telefono_jid", jid_tercero).execute()
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
            "requiere_form": True,
            "url_form": URL_FORM_OFICIAL,
            "mensaje": f"El familiar con el número {telefono_tercero} NO está registrado. Indícale que para agendar debe llenar este enlace: {URL_FORM_OFICIAL}"
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

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
        return json.dumps({"error": "Sin conexión a base de datos"})

    try:
        # Autodetección geográfica si hay un sector especificado sin provincia/municipio
        if sector and (not provincia or not municipio):
            geo_info = autodetectar_ubicacion(sector)
            provincia = provincia or geo_info.get("provincia", "")
            municipio = municipio or geo_info.get("municipio", "")

        stop_words = [
            "manana", "tarde", "noche", "hoy", "lunes", "martes", "miercoles", "jueves", "viernes", 
            "sabado", "domingo", "doctor", "doctora", "cita", "quiero", "necesito", "con", "del", 
            "esta", "para", "una", "este", "por", "favor", "dame", "ninguno", "ellos", "clinica", "centro"
        ]

        texto_limpio = remover_tildes(f"{nombre_medico} {especialidad} {mensaje_raw}").lower()
        
        if "urol" in texto_limpio:
            token_especialidad = "urol"
        elif "cardio" in texto_limpio:
            token_especialidad = "cardio"
        elif "pediat" in texto_limpio:
            token_especialidad = "pediat"
        elif "ginec" in texto_limpio:
            token_especialidad = "ginec"
        elif "derma" in texto_limpio:
            token_especialidad = "derma"
        else:
            tokens = [t for t in re.findall(r'\b\w{3,}\b', texto_limpio) if t not in stop_words]
            token_especialidad = tokens[0] if tokens else ""

        prov_clean = remover_tildes(provincia).strip()
        muni_clean = remover_tildes(municipio).strip()
        centro_clean = remover_tildes(centro_medico_preferido).strip()

        query = supabase.table("vitalmi_directorio_master").select("*")

        if prov_clean:
            query = query.or_(f"provincia.ilike.%{prov_clean}%,direccion.ilike.%{prov_clean}%")

        if muni_clean:
            query = query.or_(f"municipio.ilike.%{muni_clean}%,direccion.ilike.%{muni_clean}%")

        if centro_clean:
            query = query.or_(f"centro_medico.ilike.%{centro_clean}%,direccion.ilike.%{centro_clean}%")

        if token_especialidad:
            query = query.or_(
                f"nombre.ilike.%{token_especialidad}%,"
                f"especialidad.ilike.%{token_especialidad}%,"
                f"especialidad_medico.ilike.%{token_especialidad}%,"
                f"subespecialidades_medico.ilike.%{token_especialidad}%"
            )

        res1 = query.limit(10).execute()
        medicos = res1.data or []

        if not medicos and prov_clean and token_especialidad:
            q2 = supabase.table("vitalmi_directorio_master").select("*")
            q2 = q2.or_(f"provincia.ilike.%{prov_clean}%,direccion.ilike.%{prov_clean}%")
            if token_especialidad:
                q2 = q2.or_(
                    f"nombre.ilike.%{token_especialidad}%,"
                    f"especialidad.ilike.%{token_especialidad}%,"
                    f"especialidad_medico.ilike.%{token_especialidad}%"
                )
            res2 = q2.limit(10).execute()
            medicos = res2.data or []

        if not medicos:
            return json.dumps({
                "total_exacto": 0, 
                "mensaje": f"No se encontraron especialistas en los criterios especificados.",
                "medicos_muestra": []
            }, ensure_ascii=False)

        return json.dumps({"total_exacto": len(medicos), "medicos_muestra": medicos}, ensure_ascii=False)

    except Exception as e:
        print(f"❌ Error en consultar_directorio_inteligente: {e}")
        return json.dumps({"error": str(e)})

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
        nombre_paciente = paciente.get("nombre", "Paciente")
        cedula_paciente = paciente.get("cedula", "No registrada")
        ars_paciente = paciente.get("ars", "Privado")
        plan_ars = paciente.get("tipo_plan", "Básico")
        afiliado_ars = paciente.get("numero_afiliado", "No especificado")

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
        especialidad_medico = "Especialista Clínico"
        
        tokens_nombre = [t for t in remover_tildes(medico_nombre).split() if len(t) > 3]
        if tokens_nombre:
            res_doc = supabase.table("vitalmi_directorio_master").select("*").ilike("nombre", f"%{tokens_nombre[0]}%").limit(1).execute()
            if res_doc.data:
                centro_medico = res_doc.data[0].get("centro_medico") or centro_medico
                medico_nombre = res_doc.data[0].get("nombre") or medico_nombre
                especialidad_medico = res_doc.data[0].get("especialidad") or res_doc.data[0].get("especialidad_medico") or especialidad_medico

        datos_cita = {
            "paciente_id": paciente_id,
            "motivo_consulta": f"Paciente: {nombre_paciente} | Cédula: {cedula_paciente} | ARS: {ars_paciente} ({plan_ars}, Afiliado: {afiliado_ars}) | Médico: {medico_nombre} ({especialidad_medico}) | Centro: {centro_medico} | Tanda: {tanda_texto} | Fecha: {fecha_formateada} | Motivo: {motivo_consulta}",
            "estado": "pendiente_aprobacion",
            "created_at": obtener_hora_rd_iso()
        }

        res_cita = supabase.table("citas").insert(datos_cita).execute()
        cita_creada = res_cita.data[0] if res_cita.data else {}

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
            f"• *Tanda y Horario:* {tanda_texto}\n"
            f"• *Motivo:* {motivo_consulta}\n"
            "• *Estado:* ⏳ Cita pendiente de confirmación por el doctor.\n"
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
Cuentas con un directorio de casi 10,000 médicos especialistas en todo el país.

### 📍 MANEJO INTELIGENTE DE UBICACIONES Y SECTORES:
1. Ya posees el mapa territorial completo de República Dominicana integrado en la base de datos (vista_geo_rd y resolver_ubicacion_rd).
2. Si el usuario menciona un barrio, sector o comunidad (ej: "Piantini", "Madre Vieja", "Bella Vista", "Los Ríos"), invoca la herramienta `resolver_ubicacion_rd` o pasa el sector a `consultar_directorio_inteligente`.
3. NUNCA le preguntes al usuario en qué provincia o municipio queda un sector si el sistema ya logró autodetectarlo.

### 💬 REGLA DE SALUDO INICIAL Y DESPEDIDA DE CORTESÍA:
- Al INICIO de la conversación (saludo inicial como "Hola", "Buenas"):
  "Hola [Nombre], soy Gema tu asistente inteligente para citas médicas. Si necesitas algún doctor o especialidad sólo escríbemelo o dímelo por nota de voz."
- Cuando el usuario finalice o agradezca (ej. "Ok gracias", "Gracias", "Muchas gracias"):
  "De nada [Nombre]. Favor de estar pendiente a la confirmación de tu cita. Si hay algo más en lo que pueda asistirte no dudes en decírmelo, ya sea por texto o por voz."

### 🧠 BÚSQUEDA INTELIGENTE Y CONTEXTUALIZACIÓN PROGRESIVA:
1. Si el usuario dice "necesito un doctor": "¿Para cuál especialidad necesitas el doctor?"
2. Con la especialidad confirmada:
   - Pregunta por el Sector, Municipio o Provincia (si no lo ha mencionado aún).
   - Utiliza las herramientas de autodetección para deducir la jerarquía completa.

### 📅 REGLA DE AGENDAMIENTO SECUENCIAL (UNA PREGUNTA A LA VEZ):
Cuando el usuario confirme agendar una cita:
- NUNCA repitas preguntas ya respondidas en el historial.
- Pide los datos faltantes uno por uno:
  1. Beneficiario (Titular o Tercero). Si es tercero no registrado: {URL_FORM_OFICIAL}
  2. Fecha deseada.
  3. Tanda ('Mañana', 'Tarde' o 'Sábados').
  4. Motivo de consulta.
  5. Invoca 'agendar_cita_medica'.
"""

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    jid_normalizado = normalizar_jid(numero_usuario)
    paciente = registrar_o_actualizar_paciente(jid_normalizado, nombre_usuario)
    
    nombre_raw = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else nombre_usuario
    nombre_contacto = extraer_primer_nombre_valido(nombre_raw)

    provincia_paciente = paciente.get("provincia", "")
    municipio_paciente = paciente.get("municipio", "")
    sector_paciente = paciente.get("sector", "")

    # Autodetección automática si el mensaje contiene un sector clave del chat
    geo_auto = {}
    if mensaje_usuario:
        geo_auto = autodetectar_ubicacion(mensaje_usuario)
        if geo_auto.get("provincia"):
            provincia_paciente = geo_auto.get("provincia")
            municipio_paciente = geo_auto.get("municipio")
            sector_paciente = geo_auto.get("sector")

    guardar_mensaje_supabase(jid_normalizado, "user", mensaje_usuario)
    historial_raw = obtener_historial_supabase(jid_normalizado, limite=10)
    historial_limpio = [{"role": m["rol"] if "rol" in m else m["role"], "content": m["contenido"] if "contenido" in m else m["content"]} for m in historial_raw]

    texto_historial = " ".join([m["content"] for m in historial_limpio]).lower()
    provincia_detectada = provincia_paciente
    if not provincia_detectada:
        provincias_rd = [
            "san cristobal", "santo domingo", "distrito nacional", "santiago", "la vega", 
            "puerto plata", "la altagracia", "san pedro de macoris", "la romana", "duarte", "espaillat"
        ]
        for p in provincias_rd:
            if p in texto_historial:
                provincia_detectada = p.title()
                break

    ahora_rd = datetime.now(TZ_RD)
    contexto_temporal = f"\nHoy es {ahora_rd.strftime('%Y-%m-%d %H:%M:%S')} AST en República Dominicana."
    contexto_paciente = (
        f"\nUSUARIO EN CHAT: '{nombre_contacto}' | WhatsApp: {jid_normalizado}\n"
        f"UBICACIÓN CONTEXTUAL: Provincia: '{provincia_detectada}', Municipio: '{municipio_paciente}', Sector: '{sector_paciente}'."
    )
    
    system_prompt = SYSTEM_PROMPT_GEMA + contexto_temporal + contexto_paciente

    tools = [
        {
            "type": "function",
            "function": {
                "name": "resolver_ubicacion_rd",
                "description": "Resuelve la Provincia y Municipio exacto a partir del nombre de un barrio o sector de República Dominicana.",
                "parameters": {
                    "type": "object",
                    "properties": {"texto_sector": {"type": "string"}},
                    "required": ["texto_sector"]
                }
            }
        },
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
                "description": "Busca especialistas en el directorio según ubicación, sector y centro médico deseado.",
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

                if name == "resolver_ubicacion_rd":
                    res_geo = autodetectar_ubicacion(args.get("texto_sector", ""))
                    res_tool = json.dumps(res_geo, ensure_ascii=False)
                elif name == "verificar_registro_tercero":
                    res_tool = verificar_registro_tercero(**args)
                elif name == "consultar_directorio_inteligente":
                    args["mensaje_raw"] = mensaje_usuario
                    if ("provincia" not in args or not args["provincia"]) and provincia_detectada:
                        args["provincia"] = provincia_detectada
                    if ("municipio" not in args or not args["municipio"]) and municipio_paciente:
                        args["municipio"] = municipio_paciente
                    if ("sector" not in args or not args["sector"]) and sector_paciente:
                        args["sector"] = sector_paciente
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