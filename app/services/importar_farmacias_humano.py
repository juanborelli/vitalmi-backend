import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

from app.core.supabase import obtener_cliente_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ExtractorFarmaciasHumano")

load_dotenv(BASE_DIR / ".env")
supabase = obtener_cliente_supabase()

URL_ENDPOINT = "https://humanoseguros.com/wp-admin/admin-ajax.php"

def consultar_api_humano(codigo_prestador: int, nonce: str, cookies_str: str) -> dict:
    """
    Petición POST con multipart/form-data idéntica a la del navegador
    """
    payload = {
        "action": "dirmed_proxy",
        "_nonce": nonce,
        "endpoint": "datos-prestador",
        "method": "POST",
        "body": json.dumps({
            "codigoPrestador": str(codigo_prestador),
            "tipoPrestador": "NO-MEDICO"
        })
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
        "Origin": "https://humanoseguros.com",
        "Referer": "https://humanoseguros.com/directorio-medico/",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": cookies_str
    }

    try:
        response = requests.post(URL_ENDPOINT, data=payload, headers=headers, timeout=8)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("respuesta", {}).get("codigo") == "0":
                return res_json.get("prestador")
    except Exception as e:
        logger.warning(f"⚠️ Error en código {codigo_prestador}: {e}")
    
    return None

def normalizar_texto(texto):
    if not texto:
        return ""
    return str(texto).strip()

def obtener_siguiente_id() -> int:
    try:
        res = supabase.table("vitalmi_directorio_master").select("id").order("id", desc=True).limit(1).execute()
        if res.data and len(res.data) > 0:
            val = res.data[0].get("id")
            if isinstance(val, int):
                return val + 1
    except Exception as e:
        logger.warning(f"⚠️ No se pudo obtener ID máximo: {e}")
    return 20000

def ejecutar_extraccion_masiva(rangos: list, nonce: str, cookies_str: str):
    archivo_json = BASE_DIR / "farmacias_humano.json"
    
    # Cargar respaldo existente si ya hay datos previos acumulados
    farmacias_acumuladas = {}
    if archivo_json.exists():
        try:
            with open(archivo_json, "r", encoding="utf-8") as f:
                datos_previos = json.load(f)
                for item in datos_previos:
                    p = item.get("prestador", item)
                    if p.get("nombre"):
                        farmacias_acumuladas[p.get("nombre")] = p
            logger.info(f"📂 Se cargaron {len(farmacias_acumuladas)} farmacias previamente guardadas.")
        except Exception:
            pass

    logger.info("🚀 Iniciando barrido masivo de farmacias en ARS Humano...")

    for r_inicio, r_fin in rangos:
        logger.info(f"🔍 Escaneando rango de códigos: {r_inicio} a {r_fin}...")
        
        for codigo in range(r_inicio, r_fin + 1):
            prestador = consultar_api_humano(codigo, nonce, cookies_str)
            
            if prestador and prestador.get("tipo") == "FARMACIA":
                nombre = prestador.get("nombre")
                if nombre not in farmacias_acumuladas:
                    farmacias_acumuladas[nombre] = prestador
                    logger.info(f" ✅ [Código {codigo}] Farmacia encontrada: {nombre}")
                    
                    # Guardar progreso en disco cada 5 farmacias nuevas
                    if len(farmacias_acumuladas) % 5 == 0:
                        with open(archivo_json, "w", encoding="utf-8") as f:
                            json.dump(list(farmacias_acumuladas.values()), f, ensure_ascii=False, indent=4)

            # Pausa ligera para mantener estabilizada la conexión
            time.sleep(0.08)

    # Guardar copia final en JSON
    lista_final = list(farmacias_acumuladas.values())
    with open(archivo_json, "w", encoding="utf-8") as f:
        json.dump(lista_final, f, ensure_ascii=False, indent=4)
        
    logger.info(f"💾 Total de farmacias únicas capturadas y guardadas en JSON: {len(lista_final)}")
    
    # Proceder a importar a Supabase
    importar_a_supabase(lista_final)

def importar_a_supabase(lista_farmacias: list):
    logger.info("🔍 Obteniendo catálogo existente desde Supabase...")
    res_actuales = supabase.table("vitalmi_directorio_master").select("id, nombre, provincia, aseguradoras").execute()
    existentes = res_actuales.data or []
    
    id_actual = obtener_siguiente_id()
    mapa_existentes = {normalizar_texto(item['nombre']).lower(): item for item in existentes}

    nuevos_registros = 0
    actualizados = 0

    for prestador in lista_farmacias:
        nombre = normalizar_texto(prestador.get("nombre"))
        if not nombre:
            continue

        direcciones = prestador.get("direcciones", [])
        direccion_str = normalizar_texto(direcciones[0].get("direccion")) if direcciones else ""
        
        provincia = "República Dominicana"
        if "," in direccion_str:
            provincia = direccion_str.split(",")[-1].strip()
        elif " " in direccion_str:
            provincia = direccion_str.split()[-1].strip()

        doc_farmacia = {
            "nombre": nombre,
            "tipo_prestador": "FARMACIA",
            "especialidad": "General",
            "centro_medico": "No especificado",
            "direccion": direccion_str,
            "provincia": provincia,
            "telefono_institucional": "No disponible",
            "whatsapp": "No disponible",
            "aseguradoras": ["ARS Humano"],
            "embedding": None
        }

        clave_busqueda = nombre.lower()

        if clave_busqueda in mapa_existentes:
            item_existente = mapa_existentes[clave_busqueda]
            aseguradoras = item_existente.get("aseguradoras") or []
            if isinstance(aseguradoras, str):
                aseguradoras = [aseguradoras]

            if "ARS Humano" not in aseguradoras:
                aseguradoras.append("ARS Humano")
                supabase.table("vitalmi_directorio_master").update({
                    "aseguradoras": aseguradoras,
                    "embedding": None
                }).eq("id", item_existente["id"]).execute()
                actualizados += 1
        else:
            doc_farmacia["id"] = id_actual
            id_actual += 1
            supabase.table("vitalmi_directorio_master").insert(doc_farmacia).execute()
            nuevos_registros += 1

    logger.info("="*50)
    logger.info(f"🎉 IMPORTACIÓN A SUPABASE COMPLETADA:")
    logger.info(f"   • Nuevas farmacias insertadas: {nuevos_registros}")
    logger.info(f"   • Farmacias actualizadas con 'ARS Humano': {actualizados}")
    logger.info("="*50)

if __name__ == "__main__":
    # Copia el _nonce de la petición de cURL
    NONCE = "0b2bdf62ff"
    
    # Copia la cadena de cookies del encabezado -b de tu cURL
    COOKIES = "_ga=GA1.1.526895445.1786891256; _gcl_au=1.1.2071939623.1786891256; _pk_id.206.3e96=47bebf747d0714fe.1786891471.; _clck=8mnt3f%5E2%5Eg97%5E0%5E2419; _ga_Q3YXMYVVRD=GS2.1.s1788625951$o9$g1$t1788625975$j36$l0$h0; _ga_XCYTXFM13H=GS2.1.s1788625951$o9$g1$t1788625975$j36$l0$h0; _clsk=1uad195%5E1788625976701%5E2%5E1%5Eb.clarity.ms%2Fcollect"

    # Definimos rangos amplios para abarcar todos los códigos posibles
    RANGOS_BUSQUEDA = [
        (1000, 3000),
        (3001, 6000),
        (6001, 10000),
        (10001, 15000)
    ]

    ejecutar_extraccion_masiva(RANGOS_BUSQUEDA, NONCE, COOKIES)