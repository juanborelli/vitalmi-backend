from pydantic import BaseModel
from typing import Optional, Dict, Any

class WhatsAppWebhookPayload(BaseModel):
    event: str
    instance: str
    data: Dict[str, Any]

    class Config:
        extra = "ignore"