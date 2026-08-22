from fastapi import FastAPI
from app.api.v1.endpoints import whatsapp

app = FastAPI(title="VitalMi Backend API")

# Incluir las rutas de WhatsApp
app.include_router(whatsapp.router, prefix="/api/v1/whatsapp", tags=["WhatsApp"])

@app.get("/")
def read_root():
    return {"status": "ok", "message": "VitalMi Backend is running"}