import os
import asyncio
from datetime import datetime
import zoneinfo
from app.core.supabase import obtener_cliente_supabase
from app.services.evolution_service import enviar_mensaje_whatsapp

TZ_RD = zoneinfo.ZoneInfo("America/Santo_Domingo")

async def procesar_recordatorios_citas():
    """
    Revisa la tabla 'citas' en Supabase y envía un recordatorio automatizado 
    1 hora antes del inicio de la tanda correspondiente (8:00 AM para la mañana / 2:00 PM para la tarde)
    utilizando Evolution API.
    """
    supabase = obtener_cliente_supabase()
    if not supabase:
        print("❌ Sin conexión a Supabase para recordatorios.")
        return

    ahora = datetime.now(TZ_RD)
    fecha_hoy_str = ahora.strftime("%Y-%m-%d")
    hora_actual = ahora.hour

    try:
        # Consultar citas pendientes o confirmadas sin recordatorio enviado
        res_citas = supabase.table("citas") \
            .select("id, paciente_id, motivo_consulta, estado, recordatorio_enviado, pacientes(telefono_jid, nombre)") \
            .neq("estado", "cancelada") \
            .eq("recordatorio_enviado", False) \
            .execute()

        citas = res_citas.data or []
        if not citas:
            return

        for cita in citas:
            cita_id = cita.get("id")
            motivo = cita.get("motivo_consulta") or ""
            paciente_info = cita.get("pacientes") or {}
            telefono_jid = paciente_info.get("telefono_jid")
            nombre_paciente = paciente_info.get("nombre") or "Estimado/a paciente"

            # Evaluar si la cita corresponde al día de hoy
            if fecha_hoy_str not in motivo and "Fecha:" in motivo:
                continue

            es_tanda_manana = "Mañana" in motivo or "mañana" in motivo
            es_tanda_tarde = "Tarde" in motivo or "tarde" in motivo

            debe_enviar = False
            
            # Ventana de envío Tanda Mañana (8:00 AM - 8:59 AM)
            if es_tanda_manana and hora_actual == 8:
                debe_enviar = True
            # Ventana de envío Tanda Tarde (2:00 PM - 2:59 PM / 14:00 - 14:59)
            elif es_tanda_tarde and hora_actual == 14:
                debe_enviar = True

            if debe_enviar and telefono_jid:
                mensaje_recordatorio = (
                    f"👋 Hola {nombre_paciente}, te saludamos desde VitalMi.\n\n"
                    f"📌 *RECORDATORIO DE CITA MÉDICA*\n"
                    f"Te recordamos que hoy tienes una consulta agendada:\n"
                    f"📝 *Detalles:* {motivo}\n\n"
                    f"Por favor, asegúrate de asistir a tiempo al consultorio dentro de la tanda asignada. "
                    f"Si necesitas reprogramar o cancelar, solo respóndenos a este mensaje. ¡Estamos para ayudarte!"
                )

                resultado = await enviar_mensaje_whatsapp(destinatario=telefono_jid, texto=mensaje_recordatorio)

                if resultado:
                    # Marcar recordatorio como enviado en Supabase
                    supabase.table("citas").update({"recordatorio_enviado": True}).eq("id", cita_id).execute()
                    print(f"✅ Recordatorio enviado exitosamente a {telefono_jid} (Cita ID: {cita_id})")

    except Exception as e:
        print(f"❌ Error procesando recordatorios: {e}")

if __name__ == "__main__":
    asyncio.run(procesar_recordatorios_citas())