from fastapi import APIRouter
from app.api.v1.endpoints import whatsapp

api_router = APIRouter()

# Incluimos las rutas de whatsapp con el prefijo /whatsapp
api_router.include_router(whatsapp.router, prefix="/whatsapp", tags=["WhatsApp Webhook"])