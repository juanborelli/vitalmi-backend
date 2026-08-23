import os
import asyncio
from openai import AsyncOpenAI
from app.core.supabase_client import supabase

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SYSTEM_PROMPT_WOW = """
Eres Gema, la asistente médica ejecutiva y virtual de VitalMi en República Dominicana.

### 🎭 PERSONALIDAD Y TONO ("EFECTO WOW"):
- Hablas con una calidez caribeña/dominicana muy profesional, empática, fluida y natural.
- Valida siempre la emoción o dolor del usuario inicial ("Entiendo perfectamente, no te preocupes, vamos a resolver esto de una vez").
- EVITA listas o viñetas (*, -). Responde en 2-3 oraciones corridas como si fuera una nota de voz o mensaje directo.

### 🔄 PLAN B (BÚSQUEDA INTELIGENTE EN DIRECTORIO MASTER):
- NUNCA digas "no encontré". Si la búsqueda no es exacta, ofrece proactivamente el médico o centro más cercano en la zona que acepte la ARS indicada.

### 💎 CONVERSIÓN PROGRESIVA (AUTO-MARKETING SUTIL):
- Entrega el contacto de WhatsApp (https://wa.me/...) o el teléfono institucional primero.
- Inmediatamente después, resalta el tiempo ahorrado e introduce la suscripción:
  "Con VitalMi Premium puedo recordarte esta cita el día antes y guardar tus recetas en un solo lugar. ¿Te gustaría probarlo? Soy Gema de VitalMi 💚"
"""

def consultar_directorio_real(especialidad, ciudad_sector, ars=None):
    """Consulta directa a la base de datos reestructurada de Supabase."""
    query = supabase.table("vitalmi_directorio_master").select("*")
    
    if especialidad:
        query = query.ilike("especialidad", f"%{especialidad}%")
    if ciudad_sector:
        query = query.or_(f"sector.ilike.%{ciudad_sector}%,ciudad_provincia.ilike.%{ciudad_sector}%")

    res = query.limit(3).execute()
    datos = res.data if res.data else []

    if ars and datos:
        filtrados = [r for r in datos if any(ars.lower() in str(a).lower() for a in r.get("aseguradoras", []))]
        return filtrados if filtrados else datos
    return datos

async def evaluar_interaccion_gema(caso_nombre, mensaje_usuario, especialidad, ubicacion, ars):
    print(f"\n==================================================")
    print(f"🧪 PRUEBA EN VIVO: {caso_nombre}")
    print(f"💬 Mensaje Paciente: \"{mensaje_usuario}\"")
    
    # 1. Obtener datos reales de Supabase
    resultados = consultar_directorio_real(especialidad, ubicacion, ars)
    
    contexto_db = "DATOS OBTENIDOS DE VITALMI_DIRECTORIO_MASTER:\n"
    if resultados:
        for r in resultados:
            contexto_db += (
                f"- Nombre: {r.get('nombre')} | Especialidad: {r.get('especialidad')} | "
                f"Ubicación: {r.get('sector')}, {r.get('ciudad_provincia')} | "
                f"Tel Fijo: {r.get('telefono_institucional')} | WhatsApp: {r.get('whatsapp')} | "
                f"ARS: {r.get('aseguradoras')}\n"
            )
    else:
        contexto_db += "No hubo coincidencia exacta. Aplica PLAN B con especialistas en zonas cercanas.\n"

    # 2. Generar respuesta con la IA
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_WOW},
        {"role": "system", "content": f"Contexto de Base de Datos Real:\n{contexto_db}"},
        {"role": "user", "content": mensaje_usuario}
    ]

    try:
        res = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=300
        )
        print(f"\n🤖 Respuesta de Gema en Vivo:\n{res.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"❌ Error en evaluación: {e}")
    print(f"==================================================")

async def ejecutar_pruebas():
    print("=== 🚀 PROBANDO GEMA EN VIVO SOBRE VITALMI_DIRECTORIO_MASTER ===")
    
    # Caso 1: Búsqueda de especialidad en San Cristóbal con seguro Humano
    await evaluar_interaccion_gema(
        "Caso 1: Cardiología San Cristóbal",
        "Hola Gema, me siento con una opresión en el pecho, necesito un cardiólogo urgente en San Cristóbal que acepte ARS Humano.",
        "Cardiologia", "San Cristóbal", "Humano"
    )

    # Caso 2: Pediatría en Naco con Mapfre
    await evaluar_interaccion_gema(
        "Caso 2: Pediatría Naco",
        "Buenas, busco un pediatra para mi niña en Naco o Piantini con Mapfre.",
        "Pediatria", "Naco", "Mapfre"
    )

if __name__ == "__main__":
    asyncio.run(ejecutar_pruebas())