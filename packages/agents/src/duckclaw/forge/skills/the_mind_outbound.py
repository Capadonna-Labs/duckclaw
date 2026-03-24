"""
The Mind — outbound Telegram/n8n y reparto de cartas.

Usado por fly commands (`on_the_fly_commands`) y por herramientas LangChain (con `db` inyectada).
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any

import requests
from langchain_core.tools import tool

_log = logging.getLogger("duckclaw.the_mind_outbound")


@dataclass(frozen=True)
class TelegramDmOutcome:
    """Resultado de un intento de envío DM vía webhook."""

    ok: bool
    reason: str
    detail: str = ""

    @staticmethod
    def success() -> "TelegramDmOutcome":
        return TelegramDmOutcome(True, "ok", "")

    @staticmethod
    def skipped_no_url() -> "TelegramDmOutcome":
        return TelegramDmOutcome(False, "skipped_no_url", "ninguna URL outbound configurada")

    @staticmethod
    def skipped_no_chat_id() -> "TelegramDmOutcome":
        return TelegramDmOutcome(False, "skipped_no_chat_id", "chat_id vacío")

    @staticmethod
    def http_error(status_code: int, body_snippet: str) -> "TelegramDmOutcome":
        return TelegramDmOutcome(
            False,
            "http_error",
            f"HTTP {status_code}: {body_snippet[:200]}",
        )

    @staticmethod
    def from_exception(exc: BaseException) -> "TelegramDmOutcome":
        return TelegramDmOutcome(False, "exception", str(exc)[:300])


@dataclass
class DealCardsResult:
    """Reparto persistido + resultados de cada DM."""

    summary_line: str
    dm_outcomes: list[TelegramDmOutcome] = field(default_factory=list)

    def __str__(self) -> str:
        return self.summary_line


@dataclass
class BroadcastResult:
    """Broadcast a todos los jugadores de una partida."""

    summary_line: str
    dm_outcomes: list[TelegramDmOutcome] = field(default_factory=list)

    def __str__(self) -> str:
        return self.summary_line


def resolve_telegram_outbound_url() -> str | None:
    """
    Misma URL que `send_proactive_message` / homeostasis: N8N_OUTBOUND_WEBHOOK_URL primero.

    Después, overrides opcionales solo si hace falta un endpoint distinto para Telegram/DM.
    """
    for key in (
        "N8N_OUTBOUND_WEBHOOK_URL",
        "DUCKCLAW_TELEGRAM_SEND_WEBHOOK_URL",
        "DUCKCLAW_SEND_DM_WEBHOOK_URL",
    ):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return None


def outbound_request_headers() -> dict[str, str]:
    """
    Cabeceras para POST al webhook de salida.

    - N8N_AUTH_KEY → X-N8N-Auth (flujos n8n clásicos).
    - DUCKCLAW_WEBHOOK_SECRET → X-DuckClaw-Secret (mismo contrato que alertas del gateway).
    Si solo existe N8N_AUTH_KEY, se envían ambas cabeceras con el mismo valor para máxima compatibilidad.
    """
    h: dict[str, str] = {"Content-Type": "application/json"}
    n8n_auth = (os.environ.get("N8N_AUTH_KEY") or "").strip()
    duck_secret = (os.environ.get("DUCKCLAW_WEBHOOK_SECRET") or "").strip()
    if duck_secret:
        h["X-DuckClaw-Secret"] = duck_secret
    if n8n_auth:
        h["X-N8N-Auth"] = n8n_auth
        if not duck_secret:
            h["X-DuckClaw-Secret"] = n8n_auth
    return h


def send_telegram_dm(chat_id: str, text: str) -> TelegramDmOutcome:
    """
    POST JSON {chat_id, text, user_id} al webhook de n8n / Telegram.

    Incluye `user_id` igual a `chat_id` para flujos que solo lean user_id.
    """
    url = resolve_telegram_outbound_url()
    if not url:
        _log.warning(
            "The Mind outbound: sin URL (define N8N_OUTBOUND_WEBHOOK_URL como el resto de "
            "mensajes salientes, o DUCKCLAW_TELEGRAM_SEND_WEBHOOK_URL / DUCKCLAW_SEND_DM_WEBHOOK_URL)"
        )
        return TelegramDmOutcome.skipped_no_url()
    cid = (chat_id or "").strip()
    if not cid:
        _log.warning("The Mind outbound: chat_id vacío, no se envía DM")
        return TelegramDmOutcome.skipped_no_chat_id()

    payload = {"chat_id": cid, "user_id": cid, "text": text or ""}
    try:
        resp = requests.post(url, json=payload, headers=outbound_request_headers(), timeout=5)
        if resp.ok:
            return TelegramDmOutcome.success()
        snippet = (resp.text or "").strip().replace("\n", " ")
        _log.warning(
            "The Mind outbound: webhook respondió %s para chat_id=%s — %s",
            resp.status_code,
            cid,
            snippet[:500],
        )
        return TelegramDmOutcome.http_error(resp.status_code, snippet)
    except Exception as exc:
        _log.warning(
            "The Mind outbound: error enviando DM a chat_id=%s: %s",
            cid,
            exc,
            exc_info=_log.isEnabledFor(logging.DEBUG),
        )
        return TelegramDmOutcome.from_exception(exc)


def _aggregate_dm_line(prefix: str, outcomes: list[TelegramDmOutcome]) -> str:
    if not outcomes:
        return f"{prefix} (sin destinatarios)."
    ok = sum(1 for o in outcomes if o.ok)
    fail = len(outcomes) - ok
    if fail == 0:
        return f"{prefix}: {ok} enviado(s) OK."
    reasons = ", ".join(sorted({o.reason for o in outcomes if not o.ok}))
    return f"{prefix}: {ok} OK, {fail} fallido(s) ({reasons})."


def broadcast_message_to_players(db: Any, game_id: str, message: str) -> BroadcastResult:
    """
    Avisos generales del juego: el mismo texto a cada DM (chat_id) de la partida.
    (Las cartas van con deal_cards: mensaje distinto por jugador.)
    """
    if not game_id or not message:
        return BroadcastResult(
            "Uso: broadcast_message(game_id, message) con ambos parámetros no vacíos.",
            [],
        )

    rows = list(
        db.execute(
            "SELECT DISTINCT chat_id FROM the_mind_players WHERE game_id = ?", (game_id,)
        )
    )
    if not rows:
        return BroadcastResult(
            f"No hay jugadores registrados para la partida {game_id}.",
            [],
        )

    outcomes: list[TelegramDmOutcome] = []
    for (chat_id,) in rows:
        if chat_id:
            outcomes.append(send_telegram_dm(str(chat_id), message))

    line = _aggregate_dm_line("Avisos DM", outcomes)
    return BroadcastResult(line, outcomes)


def deal_cards_for_level(db: Any, game_id: str, level: int) -> DealCardsResult:
    """
    Reparte `level` cartas (1–100) a cada jugador, persiste en the_mind_players,
    actualiza current_level en the_mind_games y envía DM a cada jugador.
    """
    if not game_id:
        return DealCardsResult("Uso: deal_cards(game_id, level) con game_id no vacío.", [])
    try:
        lvl = int(level)
    except Exception:
        return DealCardsResult("El parámetro level debe ser un entero.", [])
    if lvl <= 0:
        return DealCardsResult("El nivel debe ser un entero positivo.", [])

    players = list(
        db.execute(
            "SELECT chat_id, username FROM the_mind_players WHERE game_id = ?", (game_id,)
        )
    )
    if not players:
        return DealCardsResult(
            f"No hay jugadores registrados para la partida {game_id}.",
            [],
        )

    outcomes: list[TelegramDmOutcome] = []
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
        outcomes.append(send_telegram_dm(str(chat_id), text))

    db.execute(
        "UPDATE the_mind_games SET current_level = ? WHERE game_id = ?",
        (lvl, game_id),
    )

    line = _aggregate_dm_line("Cartas (DM por jugador)", outcomes)
    return DealCardsResult(line, outcomes)


def make_broadcast_message_tool(db: Any):
    """Herramienta LangChain con conexión DuckDB inyectada (bóveda activa del grafo)."""

    @tool
    def broadcast_message(game_id: str, message: str) -> str:
        """
        Envía un mensaje público a todos los jugadores de la partida.
        Úsalo para anunciar el inicio del nivel, errores o victorias.
        """
        return str(broadcast_message_to_players(db, game_id, message))

    return broadcast_message


def make_deal_cards_tool(db: Any):
    """Herramienta LangChain con conexión DuckDB inyectada."""

    @tool
    def deal_cards(game_id: str, level: int) -> str:
        """
        Reparte cartas a los jugadores según el nivel actual y se las envía por mensaje privado.
        """
        return str(deal_cards_for_level(db, game_id, level))

    return deal_cards
