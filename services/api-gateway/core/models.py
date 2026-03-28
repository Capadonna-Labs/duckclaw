from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """
    Payload de chat multi-usuario para el API Gateway.

    - chat_id: identifica el grupo o el DM (se usa como thread_id interno).
    - Mismo valor en **todas** las peticiones del hilo (comandos /sandbox y mensajes normales);
      si falta, cae en \"default\" y el estado por chat (p. ej. sandbox) no coincide.
    - También se aceptan alias JSON: session_id, thread_id, chatId → chat_id (p. ej. n8n).
    - user_id / username: identifican al remitente dentro del grupo.
    - chat_type: "private", "group", "supergroup", etc.
    """

    # Nota: dejamos `message` por defecto para tolerar payloads parciales desde n8n
    # (evita errores 422 si falta el campo).
    message: str = Field("", description="Mensaje del usuario")
    chat_id: str | None = Field(
        None,
        description="ID del chat o grupo (thread_id); alias: session_id, thread_id, chatId",
        validation_alias=AliasChoices(
            "chat_id",
            "session_id",
            "thread_id",
            "chatId",
        ),
    )
    user_id: str | None = Field(None, description="ID único del usuario que envió el mensaje")
    username: str | None = Field("Usuario", description="Nombre o alias del usuario")
    chat_type: str | None = Field("private", description="Tipo de chat: private, group, supergroup, etc.")
    tenant_id: str | None = Field(
        "default",
        description="ID del tenant (cliente) para whitelist y aislamiento de workers.",
    )
    shared_db_path: str | None = Field(
        None,
        description="Ruta a .duckdb compartido; solo tiene efecto en workers con forge_context.shared_db_path_env (p. ej. LeilaAssistant).",
    )
    history: list[Any] = Field(default_factory=list, description="Historial opcional de mensajes")
    stream: bool | None = Field(False, description="Streaming SSE")
    is_system_prompt: bool | None = Field(
        False,
        description="Marca mensajes internos del sistema (ej. [SYSTEM_EVENT] del Heartbeat).",
    )

    @field_validator("chat_id", mode="before")
    @classmethod
    def _strip_chat_id(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return str(v).strip() or None

    @field_validator("username", mode="before")
    @classmethod
    def _coerce_username_to_str(cls, v: Any) -> str | None:
        """
        n8n a veces manda `username` como objeto (dict) en vez de string;
        para evitar 422 convertimos a string tomando campos comunes.
        """
        if v is None:
            return "Usuario"
        if isinstance(v, str):
            s = v.strip()
            return s if s else "Usuario"
        if isinstance(v, dict):
            # Casos típicos de Telegram: { username, first_name, ... }
            raw = v.get("username") or v.get("first_name") or v.get("name") or v.get("id")
            if raw is None:
                return "Usuario"
            s = str(raw).strip()
            return s if s else "Usuario"
        # Fallback: cualquier otro tipo -> str()
        s = str(v).strip()
        return s if s else "Usuario"

    @field_validator("tenant_id", mode="before")
    @classmethod
    def _strip_tenant_id(cls, v: Any) -> str | None:
        if v is None:
            return "default"
        if isinstance(v, str):
            s = v.strip()
            return s if s else "default"
        return str(v).strip() or "default"

