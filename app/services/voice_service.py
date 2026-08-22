import os
import io
import base64
import httpx
from openai import AsyncOpenAI

# Inicialización de OpenAI para Whisper (Transcripción)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Variables para ElevenLabs
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Voz de Rachel por defecto


async def transcribir_audio_base64(audio_base64: str) -> str:
    """
    Decodifica la nota de voz recibida de WhatsApp y la transcribe con OpenAI Whisper.
    """
    if not client or not audio_base64:
        return ""

    try:
        clean_base64 = audio_base64.split(",")[-1].strip()
        audio_bytes = base64.b64decode(clean_base64)
        
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.ogg"

        print("🎙️ Transcribiendo audio con OpenAI Whisper...")
        transcription = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="es"
        )
        texto = transcription.text.strip()
        print(f"📝 Transcripción completada: '{texto}'")
        return texto

    except Exception as e:
        print(f"❌ Error transcribiendo audio Base64 con Whisper: {e}")
        return ""


async def generar_audio_elevenlabs(texto: str) -> str:
    """
    Genera voz ultrarrealista usando la API de ElevenLabs y devuelve la cadena Base64.
    """
    if not ELEVENLABS_API_KEY:
        print("⚠️ ELEVENLABS_API_KEY no configurada. Usando fallback de OpenAI TTS...")
        return await generar_audio_openai(texto)

    # Limpiar el texto de caracteres especiales de Markdown que alteren la lectura hablada
    texto_hablado = texto.replace("*", "").replace("#", "").replace("- ", "").strip()

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    payload = {
        "text": texto_hablado,
        "model_id": "eleven_multilingual_v2",  # Modelo optimizado para español fluido
        "voice_settings": {
            "stability": 0.45,         # Menor estabilidad = más emoción y variación natural
            "similarity_boost": 0.75,   # Fidelidad de la voz
            "style": 0.20,              # Expresividad natural
            "use_speaker_boost": True
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        try:
            print(f"🗣️ Solicitando voz ultrarrealista a ElevenLabs...")
            response = await http_client.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                audio_bytes = response.content
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8").strip()
                print(f"✅ Audio de ElevenLabs generado exitosamente ({len(audio_base64)} bytes b64).")
                return audio_base64
            else:
                print(f"⚠️ Error en ElevenLabs HTTP {response.status_code}: {response.text}")
                print("🔄 Recurriendo a fallback con OpenAI TTS...")
                return await generar_audio_openai(texto)

        except Exception as e:
            print(f"❌ Excepción conectando a ElevenLabs: {e}")
            return await generar_audio_openai(texto)


async def generar_audio_openai(texto: str) -> str:
    """
    Fallback: Genera respuesta hablada usando OpenAI TTS en caso de fallar ElevenLabs.
    """
    if not client or not texto:
        return ""

    try:
        texto_hablado = texto.replace("*", "").replace("#", "").replace("- ", "").strip()
        print(f"🔊 Generando audio de respaldo con OpenAI TTS...")
        response = await client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=texto_hablado,
            response_format="opus"
        )
        
        audio_bytes = response.content
        if not audio_bytes:
            return ""

        return base64.b64encode(audio_bytes).decode("utf-8").strip()

    except Exception as e:
        print(f"❌ Error en fallback OpenAI TTS: {e}")
        return ""


# Alias de compatibilidad
transcribir_audio_whisper = transcribir_audio_base64