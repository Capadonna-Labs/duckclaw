"""
The Mind — outbound Telegram/n8n y reparto de cartas.

Usado por fly commands (`on_the_fly_commands`) y por herramientas LangChain (con `db` inyectada).
"""

from __future__ import annotations

import os
import random
from typing import Any

import requests
from langchain_core.tools import tool


def resolve_telegram_outbound_url() -> str | None:
    """Primera URL disponible: DUCKCLAW_* o N8N_OUTBOUND_WEBHOOK_URL."""
    for key in (
        "DUCKCLAW_TELEGRAM_SEND_WEBHOOK_URL",
        "DUCKCLAW_SEND_DM_WEBHOOK_URL",
        "N8N_OUTBOUND_WEBHOOK_URL",
    ):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return None


def outbound_request_headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    auth = (os.environ.get("N8N_AUTH_KEY") or "").strip()
    if auth:
        h["X-N8N-Auth"] = auth
    return h


def send_telegram_dm(chat_id: str, text: str) -> None:
    """POST JSON {chat_id, text} al webhook de n8n / Telegram (best-effort)."""
    url = resolve_telegram_outbound_url()
    if not url or not chat_id:
        return
    payload = {"chat_id": str(chat_id), "text": text}
    try:
        requests.post(url, json=payload, headers=outbound_request_headers(), timeout=5)
    except Exception:
        pass


def broadcast_message_to_players(db: Any, game_id: str, message: str) -> str:
    """
    Avisos generales del juego: el mismo texto a cada DM (chat_id) de la partida.
    (Las cartas van con deal_cards: mensaje distinto por jugador.)
    """
    if not game_id or not message:
        return "Uso: broadcast_message(game_id, message) con ambos parámetros no vacíos."

    rows = list(
        db.execute(
            "SELECT DISTINCT chat_id FROM the_mind_players WHERE game_id = ?", (game_id,)
        )
    )
    if not rows:
        return f"No hay jugadores registrados para la partida {game_id}."

    for (chat_id,) in rows:
        if chat_id:
            send_telegram_dm(str(chat_id), message)

    return "Broadcast exitoso."


def deal_cards_for_level(db: Any, game_id: str, level: int) -> str:
    """
    Reparte `level` cartas (1–100) a cada jugador, persiste en the_mind_players,
    actualiza current_level en the_mind_games y envía DM a cada jugador.
    """
    if not game_id:
        return "Uso: deal_cards(game_id, level) con game_id no vacío."
    try:
        lvl = int(level)
    except Exception:
        return "El parámetro level debe ser un entero."
    if lvl <= 0:
        return "El nivel debe ser un entero positivo."

    players = list(
        db.execute(
            "SELECT chat_id, username FROM the_mind_players WHERE game_id = ?", (game_id,)
        )
    )
    if not players:
        return f"No hay jugadores registrados para la partida {game_id}."

    for chat_id, username in players:
        if not chat_id:
            continue
        hand = sorted(random.randint(1, 100) for _ in range(lvl))
        db.execute(
            "UPDATE the_mind_players SET cards = ? WHERE game_id = ? AND chat_id = ?",
            (hand, game_id, chat_id),
        )
        uname = username or ""
        text = (
            f"Tus cartas para el Nivel {lvl} son: {hand}"
            if not uname
            else f"{uname}, tus cartas para el Nivel {lvl} son: {hand}"
        )
        send_telegram_dm(str(chat_id), text)

    db.execute(
        "UPDATE the_mind_games SET current_level = ? WHERE game_id = ?",
        (lvl, game_id),
    )

    return "Cartas repartidas en secreto."


def make_broadcast_message_tool(db: Any):
    """Herramienta LangChain con conexión DuckDB inyectada (bóveda activa del grafo)."""

    @tool
    def broadcast_message(game_id: str, message: str) -> str:
        """
        Envía un mensaje público a todos los jugadores de la partida.
        Úsalo para anunciar el inicio del nivel, errores o victorias.
        """
        return broadcast_message_to_players(db, game_id, message)

    return broadcast_message


def make_deal_cards_tool(db: Any):
    """Herramienta LangChain con conexión DuckDB inyectada."""

    @tool
    def deal_cards(game_id: str, level: int) -> str:
        """
        Reparte cartas a los jugadores según el nivel actual y se las envía por mensaje privado.
        """
        return deal_cards_for_level(db, game_id, level)

    return deal_cards
