import os
import re
from datetime import datetime
import zoneinfo
from pathlib import Path
from typing import Dict, List, Tuple
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
Eres Gema, la asistente virtual de VitalMi en República Dominicana.
Tu función es entregar información exacta sobre los médicos y prestadores del directorio según los datos en 'MÉDICOS REALES ENCONTRADOS'.

### 🎭 PERSONALIDAD Y TONO:
- Calidez caribeña/dominicana profesional, amable, directa y natural.
- Responde de forma fluida y conversacional en un máximo de 2-3 oraciones corridas.
- NO utilices listas numeradas, viñetas (*, -) ni formatos rígidos.

### 🚫 REGLAS DE ORO:
1. CERO PROMESAS DE BÚSQUEDA: JAMÁS digas "voy a buscar", "un momento por favor", "te daré los detalles" ni "voy a revisar".
2. PRECISIÓN EN CONTEOS: Si en el contexto se especifica el TOTAL REAL REGISTRADO, usa esa cifra exacta.
3. LECTURA DIRECTA: Muestra los datos de los médicos encontrados (nombre, especialidad, centro médico, dirección/contacto).
4. CERO ALUCINACIONES: NUNCA inventes médicos ni números telefónicos.
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

def buscar_medicos_master(sector_municipio: str = "", termino_busqueda: str = "", limite: int = 10) -> Tuple[List[Dict], int]:
    supabase = obtener_cliente_supabase()
    if not supabase:
        print("❌ [SUPABASE ERROR] Sin cliente Supabase activo.")
        return [], 0

    try:
        term_sin_tilde = remover_tildes(termino_busqueda).lower() if termino_busqueda else ""
        loc_sin_tilde = remover_tildes(sector_municipio).lower() if sector_municipio else ""

        print(f"🔍 [SEARCH ENGINE] Término/Nombre: '{term_sin_tilde}' | Ubicación: '{loc_sin_tilde}'")

        query = supabase.table("vitalmi_directorio_master").select(
            "id, nombre, tipo_prestador, especialidad, especialidad_clinica, especialidad_medico, subespecialidades_medico, "
            "centro_medico, direccion, ciudad_provincia, sector, telefono_institucional, telefono_alterno, whatsapp, aseguradoras",
            count="exact"
        )

        # 1. Filtro por especialidad / nombre / centro
        if term_sin_tilde:
            tokens = [t for t in term_sin_tilde.split() if len(t) > 2]
            condiciones = [
                f"especialidad_medico.ilike.%{term_sin_tilde}%",
                f"subespecialidades_medico.ilike.%{term_sin_tilde}%",
                f"especialidad_clinica.ilike.%{term_sin_tilde}%",
                f"especialidad.ilike.%{term_sin_tilde}%",
                f"nombre.ilike.%{term_sin_tilde}%",
                f"centro_medico.ilike.%{term_sin_tilde}%"
            ]
            for tok in tokens:
                condiciones.append(f"nombre.ilike.%{tok}%")
            
            query = query.or_(",".join(condiciones))

        # 2. Filtro de ubicación directo en SQL
        if loc_sin_tilde:
            query = query.or_(
                f"ciudad_provincia.ilike.%{loc_sin_tilde}%,sector.ilike.%{loc_sin_tilde}%,direccion.ilike.%{loc_sin_tilde}%"
            )

        res = query.limit(100).execute()
        datos = res.data if res.data else []
        total_count = res.count if res.count is not None else len(datos)

        print(f"📊 [DATABASE METRICS] Encontrados en DB: {total_count} | Retornados: {len(datos)}")

        # Filtrado fino en memoria para coincidencia de ubicación si se requiere
        if datos and loc_sin_tilde:
            datos_filtrados = [
                m for m in datos
                if loc_sin_tilde in remover_tildes(m.get("ciudad_provincia") or "").lower()
                or loc_sin_tilde in remover_tildes(m.get("sector") or "").lower()
                or loc_sin_tilde in remover_tildes(m.get("direccion") or "").lower()
            ]
            if datos_filtrados:
                return datos_filtrados[:limite], len(datos_filtrados)

        return datos[:limite], total_count

    except Exception as e:
        print(f"⚠️ [SUPABASE EXCEPTION] Error en buscar_medicos_master: {e}")
        return [], 0

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
    texto_contexto_limpio = remover_tildes(texto_contexto_completo)

    raices_especialidades = {
        "ginecolog": "ginecolog",
        "otorrin": "otorrin",
        "gastro": "gastro",
        "pediatr": "pediatr",
        "cardiol": "cardiol",
        "ortoped": "ortop",
        "traumatolog": "ortop",
        "internist": "internist",
        "dermatolog": "dermatolog",
        "urolog": "urolog",
        "neumolog": "neumolog",
        "nefrolog": "nefrolog",
        "fisiatr": "fisiatr",
        "hematolog": "hematolog"
    }

    termino_buscado = ""
    for clave, raiz in raices_especialidades.items():
        if clave in texto_contexto_limpio:
            termino_buscado = raiz
            break

    # Extracción de nombres de médicos si no hay especialidad
    mensaje_limpio = remover_tildes(mensaje_usuario).lower().replace("?", "").replace("¿", "")
    mensaje_limpio = re.sub(r'\b(dr|dra|doctor|doctora|en|de|la|el|los|las|cual|clinica|atiene|que|es|buscar|al|y|cuantos|cuantas|tienes|hay)\b', '', mensaje_limpio).strip()

    if not termino_buscado and mensaje_limpio:
        ciudades = ["san cristobal", "santiago", "la vega", "azua", "peravia", "bani", "santo domingo"]
        palabras_filtradas = [p for p in mensaje_limpio.split() if not any(c in p for c in ciudades) and len(p) > 2]
        if palabras_filtradas:
            termino_buscado = " ".join(palabras_filtradas)

    # Ubicación
    ubicacion_detectada = ""
    if "san cristobal" in texto_contexto_limpio:
        ubicacion_detectada = "san cristobal"
    elif "santiago" in texto_contexto_limpio:
        ubicacion_detectada = "santiago"
    elif "la vega" in texto_contexto_limpio:
        ubicacion_detectada = "la vega"
    elif "azua" in texto_contexto_limpio:
        ubicacion_detectada = "azua"

    medicos_encontrados, total_real = buscar_medicos_master(sector_municipio=ubicacion_detectada, termino_busqueda=termino_buscado)

    contexto_medicos = f"\nMÉDICOS REALES ENCONTRADOS EN SUPABASE (MUESTRA): {medicos_encontrados}\nTOTAL REAL EN BASE DE DATOS: {total_real}"
    contexto_usuario = f"\nTe estás comunicando por WhatsApp con '{nombre_contacto}' (ID: {numero_usuario})."
    
    prompt_instruccion = (
        f"\nINSTRUCCIÓN DIRECTA: Si el usuario pregunta CUÁNTOS médicos hay, responde indicando exactamente la cifra de TOTAL REAL EN BASE DE DATOS ({total_real}). "
        "Si pide recomendaciones o nombres, presenta los médicos encontrados en la muestra disponible."
    )

    system_prompt = SYSTEM_PROMPT_FASE_1 + contexto_usuario + contexto_medicos + prompt_instruccion

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