import asyncio
from fastapi import FastAPI
from app.api.v1.endpoints import whatsapp
from app.services.reminders import procesar_recordatorios_citas

app = FastAPI(title="VitalMi Backend - Gema Brain API")

app.include_router(whatsapp.router, prefix="/api/v1/whatsapp", tags=["whatsapp"])

async def tarea_segundo_plano_recordatorios():
    """
    Ejecuta la revisión de recordatorios cada 15 minutos en segundo plano.
    """
    while True:
        try:
            await procesar_recordatorios_citas()
        except Exception as e:
            print(f"❌ Error en bucle de recordatorios: {e}")
        await asyncio.sleep(900)  # Revisa cada 15 minutos (900 segundos)

@app.on_event("startup")
async def al_iniciar():
    asyncio.create_task(tarea_segundo_plano_recordatorios())

@app.get("/")
def root():
    return {"status": "ok", "service": "VitalMi Backend con Gema y Recordatorios"}