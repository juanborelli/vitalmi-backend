import base64
import json
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from app.services.evolution_service import (
    enviar_mensaje_whatsapp, 
    enviar_texto_whatsapp,
    enviar_audio_whatsapp, 
    obtener_base64_desde_message
)
from app.services.voice_service import (
    transcribir_audio_base64, 
    generar_audio_elevenlabs
)
from app.services.gema_brain import obtener_respuesta_gema, agendar_cita_medica, obtener_hora_rd_iso
from app.core.supabase import obtener_cliente_supabase

router = APIRouter()


@router.post("/webhook-google-forms")
async def recibir_google_forms(request: Request):
    """
    Recibe los 10 puntos de la Ficha de Registro de Paciente desde Google Forms (vía Apps Script),
    almacena el perfil del paciente en la tabla 'pacientes' de Supabase
    y confirma la bienvenida vía Evolution API.
    """
    try:
        data = await request.json()
        print(f"📋 Ficha de Registro de Paciente recibida: {data}")

        telefono_raw = data.get("d. Número de WhatsApp", "") or data.get("Número de WhatsApp", "")
        usuario_jid = f"{telefono_raw}@s.whatsapp.net" if telefono_raw else ""

        nombre_completo = data.get("b. Nombre Completo del Paciente", "") or data.get("Nombre Completo", "")
        cedula = data.get("c. Número de Cédula o Pasaporte", "") or data.get("Cédula", "")
        
        # Mapeo simplificado al campo único 'edad'
        edad = data.get("Edad", "") or data.get("Fecha de Nacimiento o Edad", "")
        
        ars = data.get("e. Nombre de tu ARS / Seguro Médico", "Privado")
        afiliado = data.get("f. Número de Afiliado", "No especificado")
        plan = data.get("g. Tipo de Plan", "Básico (PDSS)")
        provincia = data.get("Provincia", "")
        municipio_sector = data.get("Municipio y Sector", "")

        # 1. Almacenar o actualizar el Perfil del Paciente en Supabase
        supabase = obtener_cliente_supabase()
        if supabase and telefono_raw:
            datos_paciente = {
                "telefono_jid": usuario_jid,
                "nombre": nombre_completo,
                "cedula": cedula,
                "edad": edad,
                "ars": ars,
                "numero_afiliado": afiliado,
                "tipo_plan": plan,
                "provincia": provincia,
                "municipio_sector": municipio_sector,
                "perfil_completo": True,
                "updated_at": obtener_hora_rd_iso()
            }
            
            # Buscar si ya existe para actualizar o realizar el insert
            res_exist = supabase.table("pacientes").select("id").eq("telefono_jid", usuario_jid).execute()
            if res_exist.data:
                supabase.table("pacientes").update(datos_paciente).eq("telefono_jid", usuario_jid).execute()
            else:
                supabase.table("pacientes").insert(datos_paciente).execute()

        # 2. Enviar Confirmación de Bienvenida al Paciente por WhatsApp
        if telefono_raw:
            mensaje_bienvenida = (
                f"🎉 ¡Hola {nombre_completo}! Tu ficha de registro en VitalMi ha sido completada con éxito.\n\n"
                f"👤 *PERFIL DE PACIENTE REGISTRADO:*\n"
                f"• *Cédula:* {cedula}\n"
                f"• *Edad:* {edad} años\n"
                f"• *Seguro Médico:* {ars} ({plan})\n"
                f"• *Ubicación:* {municipio_sector}, {provincia}\n\n"
                f"Ya no tendrás que volver a llenar este formulario. A partir de ahora, cuando desees agendar una cita médica, "
                f"solo escríbeme directamente por aquí indicándome el médico o la especialidad que necesitas. ¡Estoy lista para ayudarte!"
            )
            await enviar_mensaje_whatsapp(destinatario=telefono_raw, texto=mensaje_bienvenida)

        return {"status": "success", "message": "Perfil de paciente registrado correctamente"}

    except Exception as e:
        print(f"❌ Error procesando registro de paciente: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def procesar_webhook_background(payload: dict):
    """
    Procesa el mensaje de WhatsApp recibido vía Evolution API.
    Soporta Texto, Audio (Whisper) y Respuestas Conversacionales.
    """
    try:
        data = payload.get("data", {})
        key = data.get("key", {})
        
        # Omitir mensajes enviados por la propia instancia del bot
        if key.get("fromMe", False):
            return

        remote_jid = key.get("remoteJid", "")
        if not remote_jid:
            return

        push_name = data.get("pushName", "Usuario")
        message = data.get("message", {})
        message_type = str(data.get("messageType") or "").lower()
        
        texto_usuario = ""
        es_audio = False
        
        is_audio_type = (
            "audio" in message_type 
            or "audiomessage" in str(message).lower()
        )

        if is_audio_type:
            es_audio = True
            print(f"🎙️ Nota de voz recibida de '{push_name}' ({remote_jid}). Procesando...")
            
            audio_b64 = await obtener_base64_desde_message(data)
            
            if audio_b64:
                print("🔤 Transcribiendo audio con Whisper...")
                texto_usuario = await transcribir_audio_base64(audio_b64)
                print(f"📝 Transcripción: '{texto_usuario}'")
            else:
                print("❌ No se pudo extraer el audio.")
                await enviar_mensaje_whatsapp(
                    destinatario=remote_jid, 
                    texto="Lo siento, no pude escuchar tu nota de voz. ¿Podrías enviarla nuevamente o escribir tu mensaje?"
                )
                return

        elif "conversation" in message:
            texto_usuario = message["conversation"]
        elif "extendedTextMessage" in message:
            texto_usuario = message["extendedTextMessage"].get("text", "")

        if not texto_usuario.strip():
            return

        print(f"🧠 Enviando a Gema Brain para {remote_jid} ({push_name}): '{texto_usuario}'")
        
        # Procesamiento en la lógica central de Gema
        respuesta_ia = await obtener_respuesta_gema(
            mensaje_usuario=texto_usuario,
            numero_usuario=remote_jid,
            nombre_usuario=push_name
        )

        if es_audio:
            print(f"🎙️ Generando audio de respuesta para {remote_jid}...")
            audio_b64_res = await generar_audio_elevenlabs(respuesta_ia)
            
            if audio_b64_res:
                print(f"📤 Enviando nota de voz a {remote_jid}...")
                await enviar_audio_whatsapp(destinatario=remote_jid, audio_base64=audio_b64_res)
            else:
                print("⚠️ Falló ElevenLabs. Enviando texto alternativo.")
                await enviar_mensaje_whatsapp(destinatario=remote_jid, texto=respuesta_ia)
        else:
            print(f"💬 Enviando texto a {remote_jid}...")
            await enviar_mensaje_whatsapp(destinatario=remote_jid, texto=respuesta_ia)

    except Exception as e:
        print(f"❌ Error procesando webhook de WhatsApp: {e}")


@router.post("/webhook")
@router.post("/webhook/messages-upsert")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
        
        event = payload.get("event")
        if event and event not in ["messages.upsert", "MESSAGES_UPSERT"]:
            return {"status": "ignored", "reason": f"Evento '{event}' omitido"}

        background_tasks.add_task(procesar_webhook_background, payload)
        return {"status": "processing", "message": "Webhook en proceso"}

    except Exception as e:
        print(f"❌ Error en endpoint webhook: {e}")
        raise HTTPException(status_code=400, detail="Payload no válido")