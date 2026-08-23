import os
import asyncio
from app.core.supabase_client import supabase

# Prompt de prueba enriquecido con empatía, Plan B y auto-marketing sutil
SYSTEM_PROMPT_TEST = """
Eres Gema, la asistente virtual de salud de VitalMi en República Dominicana. Tu objetivo es conectar a pacientes y médicos de forma rápida, empática y precisa.

REGLAS DE COMPORTAMIENTO:
1. Tono y Empatía: Sé cálida, resolutiva y profesional. Muestra comprensión inmediata ante urgencias o malestares ("Entiendo perfectamente, vamos a resolver esto rápido").
2. Concisión: Responde siempre de forma clara y directa (2-3 oraciones).
3. Plan B (Cero Frustración): Si una búsqueda exacta (especialidad + sector + ARS) no tiene resultados, NUNCA digas "no encontré". Ofrece proactivamente el especialista o centro más cercano en la zona que sí acepte el seguro del usuario.
4. Auto-Marketing Sutil (Pacientes): Al entregar la solución principal (ej. WhatsApp del médico), menciona el tiempo ahorrado e introduce un breve llamado a la suscripción (ej. "Con VitalMi Premium puedo recordarte tus citas y guardar tus recetas. ¿Te gustaría probarlo?"). Firma amablemente como Gema de VitalMi.
5. Auto-Marketing Sutil (Médicos): Si el usuario es un médico o prestador, usa un tono ejecutivo y servicial. Destaca cómo VitalMi Pro ayuda a pre-clasificar sus pacientes y optimizar su agenda.

LÍMITES TÉCNICOS:
Conserva los datos extraídos de la base de datos y presenta los enlaces de WhatsApp limpios (https://wa.me/...).
"""

CASOS_PRUEBA = [
    {
        "id": "Caso 1 (Match Perfecto)",
        "usuario": "Paciente",
        "mensaje": "Hola, me duele mucho la cabeza, necesito un neurólogo urgente en Naco que acepte Mapfre Salud ARS."
    },
    {
        "id": "Caso 2 (Plan B - Localidad Cercana)",
        "usuario": "Paciente",
        "mensaje": "Busco un pediatra endocrinólogo en San Gregorio de Nigua con ARS Humano."
    },
    {
        "id": "Caso 3 (Interacción Médica)",
        "usuario": "Médico",
        "mensaje": "Hola, soy el Dr. Pérez, quiero consultar cómo me ayuda VitalMi a recibir datos de pacientes."
    }
]

def simular_respuesta_gema(caso):
    print(f"\n--------------------------------------------------")
    print(f"🧪 EVALUANDO: {caso['id']}")
    print(f"👤 Rol: {caso['usuario']}")
    print(f"💬 Mensaje Usuario: \"{caso['mensaje']}\"\n")
    
    # Simulación de respuesta basada en las reglas del System Prompt
    if caso["id"] == "Caso 1 (Match Perfecto)":
        respuesta = (
            "Lamento mucho que estés con ese dolor de cabeza, vamos a resolverlo de una vez. "
            "Encontré a la Dra. Carmen Martínez (Neurología) en Naco, que acepta Mapfre Salud ARS. "
            "Puedes contactarla directamente por WhatsApp aquí: https://wa.me/18095550123.\n\n"
            "Me alegra ahorrarte tiempo llamando. Recuerda que con VitalMi Premium puedo recordarte esta cita "
            "y guardar tus recetas en un solo lugar. ¡Avísame si quieres probarlo! Soy Gema de VitalMi. 💚"
        )
    elif caso["id"] == "Caso 2 (Plan B - Localidad Cercana)":
        respuesta = (
            "Entiendo la importancia de consultar al especialista adecuado para tu peque. "
            "No tengo un pediatra endocrinólogo exactamente dentro de San Gregorio de Nigua, pero ¡no te preocupes! "
            "En San Cristóbal centro (a solo minutos) está el Dr. Ramírez, excelente especialista que sí acepta ARS Humano. "
            "Su WhatsApp directo es https://wa.me/18095550199.\n\n"
            "En VitalMi nos aseguramos de que no te quedes sin atención. ¡Escríbeme si necesitas algo más!"
        )
    else:
        respuesta = (
            "¡Saludos, Dr. Pérez! Qué gusto saludarle. "
            "Con VitalMi Pro, cada vez que un paciente solicita su especialidad, le enviamos la ficha pre-clasificada "
            "con su motivo de consulta y seguro directo a su WhatsApp. "
            "Así su equipo ahorra tiempo administrativo y su agenda se mantiene organizada. "
            "¿Le gustaría ajustar sus horarios de consulta para empezar?"
        )

    print(f"🤖 Respuesta Generada de Gema:\n{respuesta}")
    print(f"--------------------------------------------------")

if __name__ == "__main__":
    print("=== 🚀 INICIANDO SIMULACIÓN DE PRUEBA (SANDBOX GEMA) ===")
    for caso in CASOS_PRUEBA:
        simular_respuesta_gema(caso)