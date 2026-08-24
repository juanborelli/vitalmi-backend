import asyncio
import json
from datetime import datetime
import zoneinfo
from app.services.gema_brain import agendar_cita_medica, consultar_directorio_inteligente

TZ_RD = zoneinfo.ZoneInfo("America/Santo_Domingo")

def probar_backend():
    print(f"==================================================")
    print(f"🕒 HORA ACTUAL EN SANTO DOMINGO: {datetime.now(TZ_RD).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"==================================================\n")

    print("--- 1. PROBANDO BÚSQUEDA TOLERANTE (TYPO 'Anronio') ---")
    res_busqueda = consultar_directorio_inteligente(mensaje_raw="Julio Anronio Rosario")
    print(f"Resultado búsqueda: {res_busqueda}\n")

    print("--- 2. PROBANDO AGENDAMIENTO CON FORMATO FINAL GARANTIZADO ---")
    res_agendamiento = agendar_cita_medica(
        telefono_jid="8095551234@s.whatsapp.net",
        medico_nombre="Julio Antonio Rosario",
        fecha_cita="sabado",  # Resolverá al sábado más cercano (2026-08-29)
        tanda="Tanda de la Mañana",
        es_para_tercero=True,
        nombre_paciente_tercero="Carlos Reyes",
        telefono_paciente_tercero="8092223333",
        cedula_paciente="00104257893",
        ars_paciente="Mapfre Salud ARS"
    )
    
    data = json.loads(res_agendamiento)
    print(f"STATUS: {data.get('status')}")
    print(f"CITA ID: {data.get('cita_id')}\n")
    print("--- MENSAJE FORMATEADO FINAL (SIN PLACEHOLDERS) ---")
    print(data.get("mensaje_formateado_final"))
    print("==================================================")

if __name__ == "__main__":
    probar_backend()
