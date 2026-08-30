import re
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
from app.services.gema_brain import obtener_respuesta_gema, agendar_cita_medica, obtener_hora_rd_iso, normalizar_jid
from app.core.supabase import obtener_cliente_supabase

router = APIRouter()


@router.post("/webhook-google-forms")
async def recibir_google_forms(request: Request):
    """
    Recibe la Ficha de Registro desde Google Forms (vía Apps Script),
    unifica perfiles buscando por teléfono de 10 dígitos o cédula
    para evitar duplicados en Supabase, y envía confirmación por WhatsApp.
    """
    try:
        data = await request.json()
        print(f"📋 Ficha de Registro recibida de Google Forms: {data}")

        respuestas = data.get("respuestas", {}) if "respuestas" in data else data
        valores_lista = list(respuestas.values()) if isinstance(respuestas, dict) else []

        def buscar_valor(palabras_clave: list, indice_fallback: int = -1, defecto: str = "") -> str:
            if isinstance(respuestas, dict):
                for clave, valor in respuestas.items():
                    for kw in palabras_clave:
                        if kw.lower() in str(clave).lower() and valor:
                            return str(valor).strip()
            if indice_fallback >= 0 and indice_fallback < len(valores_lista):
                val = valores_lista[indice_fallback]
                if val:
                    return str(val).strip()
            return defecto

        # 1. Extracción de Datos
        nombre_completo = buscar_valor(["nombre", "paciente"], 0, "Paciente")
        cedula = buscar_valor(["cedula", "pasaporte"], 1, "No especificada")
        edad = buscar_valor(["edad"], 2, "No especificada")
        telefono_raw = buscar_valor(["whatsapp", "numero", "telefono", "celular"], 3, "")
        ars = buscar_valor(["ars", "seguro"], 4, "Privado")
        afiliado = buscar_valor(["afiliado", "carnet"], 5, "No especificado")
        plan = buscar_valor(["plan"], 6, "Básico (PDSS)")
        provincia = buscar_valor(["provincia"], 7, "San Cristóbal")
        
        municipio = buscar_valor(["municipio"], 8, "")
        sector = buscar_valor(["sector"], 9, "")

        email_paciente = (
            data.get("email", "") 
            or respuestas.get("Dirección de correo electrónico", "") 
            or respuestas.get("Email Address", "") 
            or buscar_valor(["correo", "email"], 10, "")
        ).strip()

        # Normalización telefónica
        telefono_solo_numeros = re.sub(r"\D", "", telefono_raw)
        if len(telefono_solo_numeros) >= 10:
            ultimos_10_digitos = telefono_solo_numeros[-10:]
        else:
            ultimos_10_digitos = telefono_solo_numeros

        usuario_jid = normalizar_jid(telefono_raw)

        # 2. Búsqueda y Unificación en Supabase para Evitar Filas Duplicadas
        supabase = obtener_cliente_supabase()
        if supabase:
            datos_paciente = {
                "telefono_jid": usuario_jid,
                "nombre": nombre_completo,
                "cedula": cedula,
                "edad": edad,
                "email": email_paciente,
                "ars": ars,
                "numero_afiliado": afiliado,
                "tipo_plan": plan,
                "provincia": provincia,
                "municipio": municipio,
                "sector": sector,
                "perfil_completo": True,
                "updated_at": obtener_hora_rd_iso()
            }

            # Búsqueda 1: Por JID exacto
            res_exist = supabase.table("pacientes").select("id").eq("telefono_jid", usuario_jid).execute()
            
            # Búsqueda 2: Si no existe por JID exacto, buscar por coincidencia de los 10 dígitos del teléfono
            if not res_exist.data and ultimos_10_digitos:
                res_exist = supabase.table("pacientes").select("id").ilike("telefono_jid", f"%{ultimos_10_digitos}%").execute()

            # Búsqueda 3: Si tampoco existe, buscar por Cédula si fue provista
            if not res_exist.data and cedula and cedula != "No especificada":
                res_exist = supabase.table("pacientes").select("id").eq("cedula", cedula).execute()

            # Si se encuentra un registro previo (incluso incompleto), se actualiza la misma fila
            if res_exist.data:
                paciente_id = res_exist.data[0]["id"]
                supabase.table("pacientes").update(datos_paciente).eq("id", paciente_id).execute()
            else:
                supabase.table("pacientes").insert(datos_paciente).execute()

        # 3. Enviar Confirmación de Registro por WhatsApp
        if usuario_jid:
            ubicacion_texto = f"{sector}, {municipio}, {provincia}" if sector else f"{municipio}, {provincia}"
            mensaje_bienvenida = (
                f"🎉 ¡Hola {nombre_completo}! Tu ficha de registro en VitalMi ha sido completada con éxito.\n\n"
                f"👤 *PERFIL DE PACIENTE REGISTRADO:*\n"
                f"• *Cédula:* {cedula}\n"
                f"• *Edad:* {edad} años\n"
                f"• *Correo:* {email_paciente if email_paciente else 'No registrado'}\n"
                f"• *Seguro Médico:* {ars} ({plan})\n"
                f"• *Ubicación:* {ubicacion_texto}\n\n"
                f"Ya no tendrás que volver a llenar este formulario. A partir de ahora, cuando desees agendar una cita médica, "
                f"solo escríbeme directamente por aquí indicándome el médico o la especialidad que necesitas."
            )
            await enviar_mensaje_whatsapp(destinatario=usuario_jid, texto=mensaje_bienvenida)

        return {"status": "success", "message": "Perfil unificado y registrado correctamente."}

    except Exception as e:
        print(f"❌ Error procesando webhook de Google Forms: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def procesar_webhook_background(payload: dict):
    try:
        data = payload.get("data", {})
        key = data.get("key", {})
        
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
                texto_usuario = await transcribir_audio_base64(audio_b64)
            else:
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

        respuesta_ia = await obtener_respuesta_gema(
            mensaje_usuario=texto_usuario,
            numero_usuario=remote_jid,
            nombre_usuario=push_name
        )

        if es_audio:
            audio_b64_res = await generar_audio_elevenlabs(respuesta_ia)
            if audio_b64_res:
                await enviar_audio_whatsapp(destinatario=remote_jid, audio_base64=audio_b64_res)
            else:
                await enviar_mensaje_whatsapp(destinatario=remote_jid, texto=respuesta_ia)
        else:
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