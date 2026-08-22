import os
import re
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

SYSTEM_PROMPT_BASE = """
Eres Gema, la asistente médica ejecutiva y virtual de VitalMi en República Dominicana.

### 🎭 PERSONALIDAD Y TONO ("EFECTO WOW"):
- Hablas con calidez caribeña/dominicana profesional, amable, empática, fluida y muy natural.
- Responde de forma directa, breve y conversacional (máximo 2-3 oraciones corridas). 
- EVITA estrictamente usar listas numeradas o viñetas (*, -). Escribe de forma corrida.

### 🚫 REGLA DE ORO CONTRA EVASIVAS:
- JAMÁS digas "voy a buscar", "te contactaré en breve", "te daré la información en un momento" ni pidas esperar. 
- Responde De INMEDIATO con la información contenida en 'MÉDICOS REALES ENCONTRADOS'.
- Si la lista está vacía o no hay disponibilidad en la zona solicitada, indícalo abiertamente y presenta las opciones disponibles en la lista (ej. en Santo Domingo o zonas cercanas).
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

def buscar_medicos_master(sector_municipio: str = "", termino_busqueda: str = "", ars: str = "", limite: int = 3) -> List[Dict]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        return []

    try:
        query = supabase.table("vitalmi_directorio_master").select(
            "id, nombre, tipo_prestador, especialidad, especialidad_clinica, especialidad_medico, subespecialidades_medico, "
            "centro_medico, direccion, ciudad_provincia, sector, telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
        )

        # Búsqueda limpia sobre las 3 columnas de especialidades atómicas
        if termino_busqueda:
            term_limpio = limpiar_texto(termino_busqueda).lower()
            query = query.or_(
                f"especialidad_medico.ilike.%{term_limpio}%,subespecialidades_medico.ilike.%{term_limpio}%,especialidad_clinica.ilike.%{term_limpio}%"
            )
        
        # Filtro de ubicación flexible (sector o provincia/ciudad)
        if sector_municipio:
            loc_limpia = limpiar_texto(sector_municipio)
            query = query.or_(f"sector.ilike.%{loc_limpia}%,ciudad_provincia.ilike.%{loc_limpia}%")

        res = query.limit(limite).execute()
        datos = res.data if res.data else []

        # Plan B: Búsqueda general por especialidad si no hay coincidencia directa en el municipio/sector
        if not datos and termino_busqueda:
            term_limpio = limpiar_texto(termino_busqueda).lower()
            query_plan_b = supabase.table("vitalmi_directorio_master").select(
                "id, nombre, tipo_prestador, especialidad, especialidad_clinica, especialidad_medico, subespecialidades_medico, "
                "centro_medico, direccion, ciudad_provincia, sector, telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
            ).or_(
                f"especialidad_medico.ilike.%{term_limpio}%,subespecialidades_medico.ilike.%{term_limpio}%,especialidad_clinica.ilike.%{term_limpio}%"
            ).limit(limite)
            
            res_b = query_plan_b.execute()
            datos = res_b.data if res_b.data else []

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

    # Reconstruir la conversación reciente para mantener memoria persistente de la especialidad buscada
    texto_contexto_completo = " ".join([m["content"] for m in historial]).lower() + " " + mensaje_usuario.lower()
    
    # Identificar la especialidad solicitada (en lenguaje común o término formal)
    termino_buscado = ""
    if "pediat" in texto_contexto_completo:
        termino_buscado = "pediatra"
    elif "ginec" in texto_contexto_completo or "obstet" in texto_contexto_completo:
        termino_buscado = "ginecologo"
    elif "cardiol" in texto_contexto_completo:
        termino_buscado = "cardiologo"
    elif "otorrino" in texto_contexto_completo:
        termino_buscado = "otorrino"
    elif "gastro" in texto_contexto_completo:
        termino_buscado = "gastroenterologo"
    elif "ortoped" in texto_contexto_completo or "traumatolog" in texto_contexto_completo:
        termino_buscado = "ortopeda"
    elif "dermatolog" in texto_contexto_completo:
        termino_buscado = "dermatologo"

    # Priorizar la ubicación del último mensaje o usar la presente en el historial acumulado
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

    # Ejecutar búsqueda en Supabase
    medicos_encontrados = []
    if termino_buscado or sector_detectado:
        medicos_encontrados = buscar_medicos_master(sector_municipio=sector_detectado, termino_busqueda=termino_buscado)

    contexto_medicos = f"\nMÉDICOS REALES ENCONTRADOS EN SUPABASE: {medicos_encontrados}"
    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    
    prompt_instruccion_medicos = (
        "\nINSTRUCCIÓN DIRECTA: Usa la lista 'MÉDICOS REALES ENCONTRADOS'. "
        "Si hay médicos en la lista, da sus nombres y contactos de inmediato en este mensaje. "
        "Si la lista está vacía o no hay en la ciudad solicitada, dilo abiertamente y presenta las alternativas de la lista."
    )

    system_prompt = SYSTEM_PROMPT_BASE + contexto_usuario + contexto_medicos + prompt_instruccion_medicos

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
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