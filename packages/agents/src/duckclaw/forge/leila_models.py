"""
Modelos de datos MVP: Asistente de Leila (tienda de ropa).

Spec: specs/features/Asistente de Leila — MVP Telegram.md
Plantilla: forge/templates/LeilaAssistant/
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LeilaProduct(BaseModel):
    id: str
    nombre: str
    descripcion: str = ""
    tallas: list[str] = Field(default_factory=list)
    precio: int
    foto_url: str = ""
    activo: bool = True


class LeilaOrder(BaseModel):
    order_id: str
    chat_id: str
    producto_id: str
    talla: str
    nota: str = ""
    status: str = "pending"
    created_at: datetime | None = None
