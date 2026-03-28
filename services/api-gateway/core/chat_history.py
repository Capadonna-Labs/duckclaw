"""
Historial de chat en Redis para clientes que no envían `history` en el body (p. ej. n8n + Telegram).

Clave: duckclaw:gateway:chat_hist:{tenant_id}:{session_id}
TTL por defecto: 7 días (604800 s); override con DUCKCLAW_CHAT_HISTORY_TTL_SEC.

**Contenido:** texto plano (sin escape de Markdown/Telegram). El escape para `parse_mode`
de Telegram aplica solo en la respuesta HTTP al cliente; guardar aquí `_telegram_safe`
provoca barras invertidas que se duplican turno a turno.

Los mensajes con rol ``assistant`` pasan por ``unescape_telegram_markdown_v2_layers`` al
normalizar, por si el cliente reinyectó en el body el texto ya escapado de la API.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)


def gateway_chat_history_enabled() -> bool:
    v = (os.environ.get("DUCKCLAW_GATEWAY_CHAT_HISTORY") or "true").strip().lower()
    return v not in ("0", "false", "no", "off")


def _redis_key(tenant_id: str, session_id: str) -> str:
    tid = (tenant_id or "default").strip() or "default"
    sid = (session_id or "default").strip() or "default"
    return f"duckclaw:gateway:chat_hist:{tid}:{sid}"


def history_redis_key(tenant_id: str, session_id: str) -> str:
    """Clave Redis usada por load/save (diagnóstico / integración)."""
    return _redis_key(tenant_id, session_id)


def normalize_history_item(h: Any) -> dict[str, str] | None:
    if not isinstance(h, dict):
        return None
    role = str(h.get("role") or "").strip().lower()
    content = h.get("content")
    if content is None:
        return None
    text = str(content).strip()
    if not text:
        return None
    if role == "human":
        role = "user"
    if role not in ("user", "assistant"):
        return None
    # Asistente: quitar capas de escape MarkdownV2 si el cliente guardó la respuesta HTTP tal cual (n8n).
    if role == "assistant":
        try:
            from duckclaw.graphs.on_the_fly_commands import unescape_telegram_markdown_v2_layers

            text = unescape_telegram_markdown_v2_layers(text)
        except Exception:
            pass
    max_len = int(os.environ.get("DUCKCLAW_CHAT_HISTORY_MAX_CHARS", "8000"))
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return {"role": role, "content": text}


def normalize_history_list(raw: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for h in raw:
        n = normalize_history_item(h)
        if n:
            out.append(n)
    max_msgs = int(os.environ.get("DUCKCLAW_CHAT_HISTORY_MAX_MSGS", "48"))
    if len(out) > max_msgs:
        out = out[-max_msgs:]
    return out


async def redis_load_chat_history(
    redis_client: Any, tenant_id: str, session_id: str
) -> list[dict[str, str]]:
    if redis_client is None or not gateway_chat_history_enabled():
        return []
    key = _redis_key(tenant_id, session_id)
    try:
        raw = await redis_client.get(key)
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            _log.warning("chat_history: JSON en %s no es lista; se ignora", key)
            return []
        return normalize_history_list(data)
    except Exception as exc:
        _log.warning("chat_history: fallo al leer %s: %s", key, exc)
        return []


async def redis_save_chat_history(
    redis_client: Any,
    tenant_id: str,
    session_id: str,
    items: list[dict[str, str]],
) -> None:
    if redis_client is None or not gateway_chat_history_enabled():
        return
    try:
        norm = normalize_history_list(items)
        ttl = int(os.environ.get("DUCKCLAW_CHAT_HISTORY_TTL_SEC", "604800"))
        await redis_client.set(
            _redis_key(tenant_id, session_id),
            json.dumps(norm, ensure_ascii=False),
            ex=ttl,
        )
    except Exception as exc:
        _log.warning("chat_history: fallo al guardar %s: %s", _redis_key(tenant_id, session_id), exc)
