import os
import re
import httpx


def obtener_destino_evolution(destinatario: str) -> str:
    """
    Limpia el destinatario para que la API de Evolution reciba únicamente 
    dígitos numéricos puros (ej: '18092588634'), evitando el error HTTP 400.
    Mantiene cuentas tipo @lid intactas.
    """
    destinatario_str = str(destinatario).strip()
    
    # Si es cuenta tipo @lid, se mantiene
    if "@lid" in destinatario_str:
        return destinatario_str
        
    # Extraer únicamente los dígitos numéricos
    digitos = re.sub(r"\D", "", destinatario_str)
    return digitos


async def enviar_mensaje_whatsapp(destinatario: str, texto: str):
    """
    Envía mensaje de texto a WhatsApp vía Evolution API v2.
    """
    api_url = os.getenv("EVOLUTION_API_URL", "https://evolution-api-production-56fa.up.railway.app")
    api_key = os.getenv("EVOLUTION_API_KEY", "F55845E23C3B-45B8-B5B6-0A6A01ABF008")
    instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "vitalmi")

    target = obtener_destino_evolution(destinatario)

    url = f"{api_url}/message/sendText/{instance_name}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    
    payload = {
        "number": str(target),
        "text": str(texto)
    }
    
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        try:
            print(f"📤 Intentando enviar texto a Evolution ({target})...")
            response = await http_client.post(url, json=payload, headers=headers)
            try:
                res_data = response.json()
            except Exception:
                res_data = response.text
                
            print(f"📡 Respuesta Texto Evolution ({target}): HTTP {response.status_code} -> {res_data}")
            return res_data
        except Exception as e:
            print(f"❌ Error enviando texto a Evolution API: {e}")
            return None


# Alias de compatibilidad
enviar_texto_whatsapp = enviar_mensaje_whatsapp


async def enviar_formulario_google_whatsapp(
    destinatario: str, 
    nombre_usuario: str = "Juan"
):
    """
    Envía el mensaje de bienvenida oficial de Gema con el enlace al Google Form vía Evolution API.
    """
    api_url = os.getenv("EVOLUTION_API_URL", "https://evolution-api-production-56fa.up.railway.app")
    api_key = os.getenv("EVOLUTION_API_KEY", "F55845E23C3B-45B8-B5B6-0A6A01ABF008")
    instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "vitalmi")

    target = obtener_destino_evolution(destinatario)
    url = f"{api_url}/message/sendText/{instance_name}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}

    nombre_saludo = nombre_usuario if nombre_usuario not in ["Usuario", "Trancrédito", "Paciente", ""] else "Juan"
    url_form = "https://docs.google.com/forms/d/e/1FAIpQLSdrp4sSaHzxOli3UlYPbvvZgznovAWxQH1IAXvFi0OveZC_cg/viewform"

    texto_mensaje = (
        f"Hola {nombre_saludo}, ¿cómo te sientes hoy? Espero que te encuentres bien de salud.\n\n"
        f"Para agendar tu cita médica favor de llenar este breve formulario:\n"
        f"📋 {url_form}\n\n"
        "Y recuerda, soy Gema de VitalMi. Tu asistente para citas médicas en toda República Dominicana."
    )

    payload = {
        "number": str(target),
        "text": texto_mensaje,
        "options": {
            "delay": 1000,
            "presence": "composing",
            "linkPreview": True
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        try:
            print(f"📤 Enviando enlace de Google Form a Evolution API ({target})...")
            response = await http_client.post(url, json=payload, headers=headers)
            try:
                res_data = response.json()
            except Exception:
                res_data = response.text
            print(f"📡 Resultado Envío Google Form Evolution ({target}): HTTP {response.status_code} -> {res_data}")
            return res_data
        except Exception as e:
            print(f"❌ Error enviando mensaje de formulario: {e}")
            return None


async def enviar_audio_whatsapp(destinatario: str, audio_base64: str):
    """
    Envía una nota de voz nativa (PTT) a WhatsApp vía Evolution API v2.
    Protegido contra valores NoneType y formateado para Base64 puro.
    """
    if not audio_base64 or not isinstance(audio_base64, str):
        print("❌ Error: audio_base64 es invalido o None. Se omite el envío de audio.")
        return None

    api_url = os.getenv("EVOLUTION_API_URL", "https://evolution-api-production-56fa.up.railway.app")
    api_key = os.getenv("EVOLUTION_API_KEY", "F55845E23C3B-45B8-B5B6-0A6A01ABF008")
    instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "vitalmi")

    target = obtener_destino_evolution(destinatario)

    url = f"{api_url}/message/sendWhatsAppAudio/{instance_name}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    
    clean_audio_b64 = str(audio_base64).split(",")[-1].strip().replace("\n", "").replace("\r", "")

    payload = {
        "number": str(target),
        "audio": clean_audio_b64,
        "delay": 1,
        "encoding": True
    }
    
    async with httpx.AsyncClient(timeout=60.0) as http_client:
        try:
            print(f"📤 Enviando nota de voz Base64 a Evolution API ({target})...")
            response = await http_client.post(url, json=payload, headers=headers)
            try:
                res_data = response.json()
            except Exception:
                res_data = response.text

            print(f"📡 Resultado Envío Audio Evolution ({target}): HTTP {response.status_code} -> {res_data}")
            return res_data
        except Exception as e:
            print(f"❌ Error excepcional enviando audio a Evolution API: {e}")
            return None


async def obtener_base64_desde_message(message_data: dict) -> str:
    """
    Solicita a Evolution API descifrar el archivo .enc de WhatsApp a Base64.
    """
    api_url = os.getenv("EVOLUTION_API_URL", "https://evolution-api-production-56fa.up.railway.app")
    api_key = os.getenv("EVOLUTION_API_KEY", "F55845E23C3B-45B8-B5B6-0A6A01ABF008")
    instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "vitalmi")

    url = f"{api_url}/chat/getBase64FromMediaMessage/{instance_name}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"message": message_data, "convertToMp3": False}

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        try:
            print("🔓 Solicitando descifrado de audio .enc a Evolution API...")
            response = await http_client.post(url, json=payload, headers=headers)
            if response.status_code in [200, 201]:
                res_json = response.json()
                base64_clean = res_json.get("base64", "")
                if base64_clean:
                    print("✅ Audio descifrado exitosamente.")
                    return base64_clean
            print(f"⚠️ No se pudo descifrar audio, HTTP {response.status_code}: {response.text}")
            return ""
        except Exception as e:
            print(f"❌ Error en obtener_base64_desde_message: {e}")
            return ""


async def descargar_audio_whatsapp(payload: dict) -> bytes:
    """
    Descarga los bytes del audio llamando a obtener_base64_desde_message y decodificándolo.
    """
    import base64
    message_data = payload.get("data", {})
    b64_str = await obtener_base64_desde_message(message_data)
    if b64_str:
        try:
            clean_b64 = b64_str.split(",")[-1].strip()
            return base64.b64decode(clean_b64)
        except Exception as e:
            print(f"❌ Error decodificando Base64 descargado: {e}")
            return b""
    return b""