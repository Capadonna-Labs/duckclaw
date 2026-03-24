from __future__ import annotations

"""
The Mind — broadcast y reparto (compatibilidad).

Las implementaciones viven en `the_mind_outbound.py`. Por defecto estas herramientas
usan la BD del gateway; `build_general_graph` debe registrar las variantes con `db`
inyectada vía `make_broadcast_message_tool` / `make_deal_cards_tool`.
"""

from langchain_core.tools import tool

from duckclaw.forge.skills.the_mind_outbound import (
    broadcast_message_to_players,
    deal_cards_for_level,
    make_broadcast_message_tool,
    make_deal_cards_tool,
)
from duckclaw.gateway_db import get_gateway_db


@tool
def broadcast_message(game_id: str, message: str) -> str:
    """
    Envía un mensaje público a todos los jugadores de la partida.
    Úsalo para anunciar el inicio del nivel, errores o victorias.
    """
    db = get_gateway_db()
    return str(broadcast_message_to_players(db, game_id, message))


@tool
def deal_cards(game_id: str, level: int) -> str:
    """
    Reparte cartas a los jugadores según el nivel actual y se las envía por mensaje privado.
    """
    db = get_gateway_db()
    return str(deal_cards_for_level(db, game_id, level))


__all__ = [
    "broadcast_message",
    "deal_cards",
    "broadcast_message_to_players",
    "deal_cards_for_level",
    "make_broadcast_message_tool",
    "make_deal_cards_tool",
]
