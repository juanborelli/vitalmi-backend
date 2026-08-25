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
from app.services.gema_brain import obtener_respuesta_gema, agendar_cita_medica

router = APIRouter()


async def procesar_webhook_background(payload: dict):
    """
    Procesa el mensaje de WhatsApp recibido vía Evolution API.
    Soporta Texto, Audio (Whisper) y Respuestas de Formularios Nativo (WhatsApp Flows).
    """
    try:
        data = payload.get("data", {})
        key = data.get("key", {})
        
        # Ignorar mensajes propios enviados por el bot
        if key.get("fromMe", False):
            return

        remote_jid = key.get("remoteJid", "")
        if not remote_jid:
            return

        push_name = data.get("pushName", "Usuario")
        message = data.get("message", {})
        message_type = str(data.get("messageType") or "").lower()
        
        # -------------------------------------------------------------
        # CASO 1: EL USUARIO RESPONDIÓ UN FORMULARIO NATIVO (FLOWS)
        # -------------------------------------------------------------
        if "interactiveresponsemessage" in message_type or "interactiveResponseMessage" in message:
            interactive_data = message.get("interactiveResponseMessage", {})
            native_flow_response = interactive_data.get("nativeFlowResponseMessage", {})
            
            response_json_str = native_flow_response.get("paramsJson", "{}")
            datos_formulario = json.loads(response_json_str)

            print(f"📋 Formulario de WhatsApp Flow recibido de '{push_name}': {datos_formulario}")

            es_tercero = (datos_formulario.get("tipo_paciente") == "tercero")
            
            # Ejecución limpia de agendamiento directo en backend
            res_agendamiento = agendar_cita_medica(
                telefono_jid=remote_jid,
                medico_nombre=datos_formulario.get("medico_nombre", "Médico General"),
                fecha_cita=datos_formulario.get("fecha_cita", "proxima_disponible"),
                tanda=datos_formulario.get("tanda", "Tanda de la Mañana"),
                es_para_tercero=es_tercero,
                nombre_paciente_tercero=datos_formulario.get("nombre_completo") if es_tercero else "",
                telefono_paciente_tercero=datos_formulario.get("telefono") if es_tercero else "",
                cedula_paciente=datos_formulario.get("cedula", ""),
                ars_paciente=datos_formulario.get("ars", "Privado"),
                numero_afiliado_ars=datos_formulario.get("numero_afiliado", "No especificado"),
                motivo_consulta=datos_formulario.get("motivo_consulta", "Consulta General / Primera Visita")
            )

            res_data = json.loads(res_agendamiento)
            mensaje_confirmacion = res_data.get("mensaje_formateado_final")

            await enviar_mensaje_whatsapp(destinatario=remote_jid, texto=mensaje_confirmacion)
            return

        # -------------------------------------------------------------
        # CASO 2: MENSAJE CONVENCIONAL DE TEXTO O NOTA DE VOZ
        # -------------------------------------------------------------
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
        
        # Procesar con la inteligencia de Gema (conversación)
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