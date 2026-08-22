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

SYSTEM_PROMPT_FASE_1 = """
Eres Gema, la asistente virtual de VitalMi en República Dominicana. Tu ÚNICA función es entregar la información de los médicos que se encuentran en el bloque 'MÉDICOS REALES ENCONTRADOS'.

### 🎭 PERSONALIDAD Y TONO:
- Calidez caribeña/dominicana profesional, amable, directa y natural.
- Responde de forma fluida y conversacional (máximo 2-3 oraciones corridas).
- NO utilices listas numeradas, viñetas (*, -) ni formatos rígidos.

### 🚫 REGLAS STRICTAS DE RESPUESTA:
1. CERO PROMESAS DE BÚSQUEDA: NUNCA digas "voy a buscar", "un momento por favor", "te daré los detalles" ni "voy a revisar".
2. SI 'MÉDICOS REALES ENCONTRADOS' TIENE DATOS: Presenta los nombres de los doctores, su centro médico y su contacto de inmediato.
3. SI 'MÉDICOS REALES ENCONTRADOS' ESTÁ VACÍO: Responde exactamente: "En este momento no tengo registrado un especialista de esa área en esa zona en nuestro directorio."
"""

def obtener_hora_rd_iso() -> str:
    return datetime.now(TZ_RD).isoformat()

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

def buscar_medicos_master(sector_municipio: str = "", termino_busqueda: str = "", limite: int = 5) -> List[Dict]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        print("❌ [SUPABASE ERROR] No se pudo conectar a Supabase")
        return []

    try:
        term_sin_tilde = remover_tildes(termino_busqueda).lower() if termino_busqueda else ""
        
        # Mapeo de raíz
        if "otorrin" in term_sin_tilde:
            term_sin_tilde = "otorrin"
        elif "gastro" in term_sin_tilde:
            term_sin_tilde = "gastro"
        elif "ortoped" in term_sin_tilde or "traumatolog" in term_sin_tilde:
            term_sin_tilde = "ortop"

        print(f"🔍 [SUPABASE SEARCH] Término extraído: '{term_sin_tilde}' | Ubicación: '{sector_municipio}'")

        # Traer un lote directo sin filtros complejos de OR en SQL para no descartar NULLs
        res = supabase.table("vitalmi_directorio_master").select(
            "id, nombre, tipo_prestador, especialidad, especialidad_clinica, especialidad_medico, subespecialidades_medico, "
            "centro_medico, direccion, ciudad_provincia, sector, telefono_institucional, telefono_alterno, whatsapp, aseguradoras"
        ).limit(100).execute()

        todos = res.data if res.data else []
        print(f"📊 [SUPABASE RAW] Registros brutos leídos de la tabla: {len(todos)}")

        if not todos:
            return []

        # Filtrar por especialidad en Python
        medicos_especialidad = []
        if term_sin_tilde:
            for m in todos:
                esp = remover_tildes(m.get("especialidad") or "").lower()
                esp_med = remover_tildes(m.get("especialidad_medico") or "").lower()
                esp_cli = remover_tildes(m.get("especialidad_clinica") or "").lower()
                sub_esp = remover_tildes(m.get("subespecialidades_medico") or "").lower()

                if term_sin_tilde in esp or term_sin_tilde in esp_med or term_sin_tilde in esp_cli or term_sin_tilde in sub_esp:
                    medicos_especialidad.append(m)
        else:
            medicos_especialidad = todos

        print(f"📊 [MATCH ESPECIALIDAD] Coincidencias por especialidad: {len(medicos_especialidad)}")

        # Filtrar por ubicación en Python si se especificó
        if medicos_especialidad and sector_municipio:
            loc_limpia = remover_tildes(sector_municipio).lower()
            datos_filtrados = [
                m for m in medicos_especialidad 
                if loc_limpia in remover_tildes(m.get("ciudad_provincia") or "").lower() 
                or loc_limpia in remover_tildes(m.get("sector") or "").lower()
                or loc_limpia in remover_tildes(m.get("direccion") or "").lower()
            ]
            if datos_filtrados:
                print(f"✅ [MATCH ZONA] Coincidencias exactas en zona '{sector_municipio}': {len(datos_filtrados)}")
                return datos_filtrados[:limite]

        # Fallback: Entregar los de la especialidad general
        print(f"⚠️ [FALLBACK] Retornando {len(medicos_especialidad)} registros de la especialidad")
        return medicos_especialidad[:limite]

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

    texto_contexto_completo = " ".join([m["content"] for m in historial]).lower() + " " + mensaje_usuario.lower()
    
    palabras_clave = [
        "otorrinolaringolog", "otorrino", "gastroenterolog", "gastro", "pediatr", "ginecolog", "cardiolog", 
        "ortoped", "traumatolog", "internist", "dermatolog", "urolog",
        "anestesiolog", "hematolog", "fisiatr", "nefrolog", "neumolog",
        "patolog", "reumatolog", "medico general", "obstetr", "cirujan"
    ]
    
    termino_buscado = ""
    for palabra in palabras_clave:
        if palabra in texto_contexto_completo:
            termino_buscado = palabra
            break

    if not termino_buscado:
        termino_buscado = mensaje_usuario

    sector_detectado = ""
    texto_limpio_loc = remover_tildes(texto_contexto_completo).lower()
    if "san cristobal" in texto_limpio_loc:
        sector_detectado = "SAN CRISTOBAL"
    elif "santo domingo" in texto_limpio_loc:
        sector_detectado = "SANTO DOMINGO"
    elif "azua" in texto_limpio_loc:
        sector_detectado = "AZUA"

    medicos_encontrados = buscar_medicos_master(sector_municipio=sector_detectado, termino_busqueda=termino_buscado)

    contexto_medicos = f"\nMÉDICOS REALES ENCONTRADOS EN SUPABASE: {medicos_encontrados}"
    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    
    prompt_instruccion_medicos = (
        "\nINSTRUCCIÓN DIRECTA: Responde ÚNICAMENTE usando los datos de 'MÉDICOS REALES ENCONTRADOS'. "
        "Si la lista tiene médicos, entrega sus nombres y teléfonos inmediatamente. "
        "Si está vacía, di abiertamente que no tienes registrados en esa zona."
    )

    system_prompt = SYSTEM_PROMPT_FASE_1 + contexto_usuario + contexto_medicos + prompt_instruccion_medicos

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.0,
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