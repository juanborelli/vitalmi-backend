import os
from datetime import datetime
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

# PROMPT ESTRICTO PARA FASE 1: LECTURA FIEL DEL DIRECTORIO
SYSTEM_PROMPT_FASE_1 = """
Eres Gema, la asistente virtual de VitalMi en República Dominicana.
Tu ÚNICA función actual es proporcionar información exacta del directorio médico disponible en la base de datos.

### 🎭 PERSONALIDAD Y TONO:
- Calidez caribeña/dominicana profesional, amable, directa y natural.
- Responde de forma fluida y conversacional en un máximo de 2-3 oraciones corridas.
- NO utilices listas numeradas, viñetas (*, -) ni formatos rígidos.

### 🚫 REGLAS DE ORO DE FASE 1 (LECTURA DIRECTA):
1. CERO ALUCINACIONES: NUNCA inventes nombres de médicos, clínicas o números telefónicos.
2. CERO GESTIÓN DE CITAS: NO menciones disponibilidad, horarios ni agendamiento de citas.
3. CERO EVASIVAS: JAMÁS digas "voy a buscar", "te contactaré en breve" o "espera un momento".
4. SI HAY RESULTADOS en 'MÉDICOS REALES ENCONTRADOS': Entrega inmediatamente el nombre del médico, su especialidad/subespecialidad, el centro médico y su contacto (teléfono/WhatsApp).
5. SI LA LISTA ESTÁ VACÍA: Informa amablemente que en este momento no hay un especialista con ese criterio exacto registrado en esa zona en la base de datos.
"""

def obtener_hora_rd_iso() -> str:
    return datetime.now(TZ_RD).isoformat()

def limpiar_texto(texto: str) -> str:
    if not texto:
        return ""
    replacements = (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
        ("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U")
    )
    for a, b in replacements:
        texto = texto.replace(a, b)
    return texto.strip().upper()

def buscar_medicos_master(sector_municipio: str = "", termino_busqueda: str = "", limite: int = 5) -> List[Dict]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return []

    try:
        query = supabase.table("vitalmi_directorio_master").select(
            "id, nombre, tipo_prestador, especialidad, especialidad_clinica, especialidad_medico, subespecialidades_medico, "
            "centro_medico, direccion, ciudad_provincia, sector, telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
        )

        term_limpio = limpiar_texto(termino_busqueda).lower() if termino_busqueda else ""
        
        # Mapeo de comodines de raíz médica
        if "otorrino" in term_limpio:
            term_limpio = "otorrin"
        elif "gastro" in term_limpio:
            term_limpio = "gastro"
        elif "ortoped" in term_limpio or "traumatolog" in term_limpio:
            term_limpio = "ortop"

        # Búsqueda amplia en todas las columnas de especialidades
        if term_limpio:
            query = query.or_(
                f"especialidad_medico.ilike.%{term_limpio}%,subespecialidades_medico.ilike.%{term_limpio}%,especialidad_clinica.ilike.%{term_limpio}%,especialidad.ilike.%{term_limpio}%"
            )

        res = query.limit(limite).execute()
        datos = res.data if res.data else []

        # Filtrado flexible por ubicación en Python
        if datos and sector_municipio:
            loc_limpia = limpiar_texto(sector_municipio).lower()
            datos_filtrados = [
                m for m in datos 
                if loc_limpia in limpiar_texto(m.get("ciudad_provincia", "")).lower() 
                or loc_limpia in limpiar_texto(m.get("sector", "")).lower()
                or loc_limpia in limpiar_texto(m.get("direccion", "")).lower()
            ]
            if datos_filtrados:
                return datos_filtrados

        return datos
    except Exception as e:
        print(f"⚠️ [SUPABASE EXCEPTION] Error en buscar_medicos_master: {e}")
        return []

def registrar_o_actualizar_paciente(telefono_jid: str, nombre_push: str = "") -> dict:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return {}

    try:
        nombre_guardar = nombre_push.strip() if (nombre_push and nombre_push.strip()) else "Usuario WhatsApp"
        res = supabase.table("pacientes").select("*").eq("telefono_jid", telefono_jid).execute()
        
        if res.data and len(res.data) > 0:
            paciente_existente = res.data[0]
            if paciente_existente.get("nombre") in ["Paciente", "Usuario WhatsApp", None] and nombre_guardar != "Usuario WhatsApp":
                supabase.table("pacientes").update({
                    "nombre": nombre_guardar,
                    "updated_at": obtener_hora_rd_iso()
                }).eq("telefono_jid", telefono_jid).execute()
            return paciente_existente

        datos_nuevo = {
            "telefono_jid": telefono_jid,
            "nombre": nombre_guardar,
            "created_at": obtener_hora_rd_iso()
        }
        res_insert = supabase.table("pacientes").insert(datos_nuevo).execute()
        return res_insert.data[0] if res_insert.data else {}
    except Exception as e:
        print(f"❌ [SUPABASE EXCEPTION] Error registrando en 'pacientes': {e}")
        return {}

def obtener_historial_supabase(telefono_jid: str, limite: int = 10) -> List[Dict[str, str]]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return []

    try:
        response = (
            supabase.table("historial_chats")
            .select("rol, contenido")
            .eq("telefono_jid", telefono_jid)
            .order("created_at", desc=True)
            .limit(limite)
            .execute()
        )
        registros = response.data[::-1] if response.data else []
        return [{"role": item["rol"], "content": item["contenido"]} for item in registros]
    except Exception as e:
        print(f"⚠️ [SUPABASE EXCEPTION] Error obteniendo historial: {e}")
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
        print(f"❌ [SUPABASE EXCEPTION] Error guardando en 'historial_chats': {e}")

async def obtener_respuesta_gema(mensaje_usuario: str, numero_usuario: str = "default", nombre_usuario: str = "") -> str:
    client = obtener_cliente_openai()
    if not client:
        return "Hola, en este momento estamos actualizando el sistema. Escríbeme en un minuto y con gusto te ayudo."

    paciente = registrar_o_actualizar_paciente(numero_usuario, nombre_usuario)
    nombre_contacto = paciente.get("nombre", nombre_usuario) if paciente.get("nombre") else "Estimado/a"

    guardar_mensaje_supabase(numero_usuario, "user", mensaje_usuario)

    historial = obtener_historial_supabase(numero_usuario, limite=10)

    # Contexto unificado
    texto_contexto_completo = " ".join([m["content"] for m in historial]).lower() + " " + mensaje_usuario.lower()
    
    # Detección dinámica de especialidades
    palabras_clave = [
        "otorrino", "gastro", "pediatra", "ginecologo", "cardiologo", 
        "ortopeda", "traumatologo", "internista", "dermatologo", "urologo",
        "anestesiologo", "hematologo", "fisiatra", "nefrologo", "neumologo",
        "patologo", "reumatologo", "medico general", "obstetra", "cirujano"
    ]
    
    termino_buscado = ""
    for palabra in palabras_clave:
        if palabra in texto_contexto_completo:
            termino_buscado = palabra
            break

    # Detección de zona geográfica
    mensaje_actual_lc = mensaje_usuario.lower()
    sector_detectado = ""
    if "san cristobal" in mensaje_actual_lc or "san cristóbal" in mensaje_actual_lc:
        sector_detectado = "SAN CRISTOBAL"
    elif "santo domingo" in mensaje_actual_lc:
        sector_detectado = "SANTO DOMINGO"
    elif "azua" in mensaje_actual_lc:
        sector_detectado = "AZUA"
    else:
        if "san cristobal" in texto_contexto_completo or "san cristóbal" in texto_contexto_completo:
            sector_detectado = "SAN CRISTOBAL"
        elif "azua" in texto_contexto_completo:
            sector_detectado = "AZUA"

    # Consulta a la base de datos
    medicos_encontrados = buscar_medicos_master(sector_municipio=sector_detectado, termino_busqueda=termino_buscado)

    contexto_medicos = f"\nMÉDICOS REALES ENCONTRADOS EN SUPABASE: {medicos_encontrados}"
    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    
    prompt_instruccion_medicos = (
        "\nINSTRUCCIÓN DE LECTURA DIRECTA: Muestra de inmediato la información de la lista 'MÉDICOS REALES ENCONTRADOS'. "
        "Menciona el nombre del médico, especialidad, clínica y número de contacto. "
        "No hables de agendar citas ni de buscar disponibilidad posterior."
    )

    system_prompt = SYSTEM_PROMPT_FASE_1 + contexto_usuario + contexto_medicos + prompt_instruccion_medicos

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.1,
            max_tokens=350
        )
        respuesta_texto = response.choices[0].message.content.strip()

        guardar_mensaje_supabase(numero_usuario, "assistant", respuesta_texto)
        return respuesta_texto
    except Exception as e:
        print(f"❌ Error en gema_brain: {e}")
        return "Tuve un pequeño inconveniente técnico. ¿Podrías repetirme tu mensaje, por favor?"

async def procesar_mensaje_gema(usuario_jid: str, mensaje: str) -> str:
    return await obtener_respuesta_gema(mensaje_usuario=mensaje, numero_usuario=usuario_jid)