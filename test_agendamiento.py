import asyncio
import json
from app.services.gema_brain import agendar_cita_medica, consultar_directorio_inteligente

def probar_backend():
    print("--- 1. PROBANDO BÚSQUEDA TOLERANTE ---")
    res_busqueda = consultar_directorio_inteligente(mensaje_raw="Julio Anronio Rosario")
    print(f"Resultado búsqueda typo: {res_busqueda}\n")

    print("--- 2. PROBANDO AGENDAMIENTO PARA TERCERO CON DATOS COMPLETOS ---")
    # Simulación de agendamiento para un tercero con Cédula y ARS validados
    res_agendamiento = agendar_cita_medica(
        telefono_jid="8095551234@s.whatsapp.net",
        medico_nombre="Julio Antonio Rosario",
        fecha_cita="sabado",  # Resolverá a 2026-08-29
        tanda="Tanda de la Mañana",
        es_para_tercero=True,
        nombre_paciente_tercero="Carlos Reyes",
        telefono_paciente_tercero="8092223333",
        cedula_paciente="00104257893",
        ars_paciente="Mapfre Salud ARS"
    )
    
    data = json.loads(res_agendamiento)
    print("STATUS:", data.get("status"))
    print("MENSAJE FORMATEADO FINAL:\n")
    print(data.get("mensaje_formateado_final"))

if __name__ == "__main__":
    probar_backend()