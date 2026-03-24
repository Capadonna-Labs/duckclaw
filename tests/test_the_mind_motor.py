"""Tests del motor The Mind (fly commands) sobre DuckDB en memoria."""

from __future__ import annotations

import re
from typing import Any

import pytest

from duckclaw import DuckClaw
from duckclaw.forge.skills.the_mind_outbound import TelegramDmOutcome
from duckclaw.graphs.on_the_fly_commands import _upsert_authorized_user, handle_command


@pytest.fixture
def db() -> Any:
    return DuckClaw(":memory:")


def _game_id_from_reply(text: str) -> str:
    # Respuestas pasan por _telegram_safe (escapa _ como \_)
    cleaned = text.replace("\\_", "_")
    m = re.search(r"(game_\d+_[a-z0-9]+)", cleaned)
    assert m, text
    return m.group(1)


def test_new_mind_join_start_mind_and_play_level1(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []

    def _fake_send(chat_id: str, text: str) -> TelegramDmOutcome:
        sent.append((str(chat_id), text))
        return TelegramDmOutcome.success()

    monkeypatch.setattr(
        "duckclaw.forge.skills.the_mind_outbound.send_telegram_dm",
        _fake_send,
    )

    r1 = handle_command(db, "111", "/new_mind")
    assert "partida creada" in r1.lower() or "game_" in r1
    gid = _game_id_from_reply(r1)

    r_join = handle_command(db, "222", f"/join {gid}")
    assert "unido" in r_join.lower()

    r_start = handle_command(db, "111", f"/start_mind {gid}")
    assert "iniciada" in r_start.lower() or "nivel 1" in r_start.lower()

    rows = list(db.execute("SELECT chat_id, cards FROM the_mind_players WHERE game_id = ?", (gid,)))
    assert len(rows) == 2
    hands = {str(r[0]): list(r[1] or []) for r in rows}
    assert all(len(h) == 1 for h in hands.values())

    # Orden ascendente: primero quien tenga la carta más baja
    by_chat = sorted(hands.items(), key=lambda kv: kv[1][0])
    first_chat, low = by_chat[0][0], by_chat[0][1][0]
    second_chat, high = by_chat[1][0], by_chat[1][1][0]

    p1 = handle_command(db, first_chat, f"/play {low}")
    assert "jugó" in p1.lower() or "✅" in p1

    p2 = handle_command(db, second_chat, f"/play {high}")
    assert "nivel 1" in p2.lower() or "completado" in p2.lower() or "🎉" in p2 or "nivel 2" in p2.lower()

    st = list(db.execute("SELECT status, current_level FROM the_mind_games WHERE game_id = ?", (gid,)))
    assert st
    # Tras completar nivel 1 debe haber avanzado a nivel 2 o marcado progreso
    assert int(st[0][1] or 0) >= 2 or str(st[0][0] or "").lower() == "won"


def test_play_mind_invalid_loses_life(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "duckclaw.forge.skills.the_mind_outbound.send_telegram_dm",
        lambda *a, **k: TelegramDmOutcome.success(),
    )
    monkeypatch.setattr(
        "duckclaw.forge.skills.the_mind_outbound.broadcast_message_to_players",
        lambda *a, **k: "ok",
    )

    r1 = handle_command(db, "501", "/new_mind")
    gid = _game_id_from_reply(r1)
    handle_command(db, "502", f"/join {gid}")
    handle_command(db, "501", f"/start_mind {gid}")

    rows = list(db.execute("SELECT chat_id, cards FROM the_mind_players WHERE game_id = ?", (gid,)))
    hands = {str(r[0]): list(r[1] or []) for r in rows}
    by_val = sorted(((c, chat) for chat, hs in hands.items() for c in hs), key=lambda x: x[0])
    low_card, low_chat = by_val[0]
    high_card, high_chat = by_val[1]

    # Juega primero el que tiene la carta alta (debe fallar)
    bad = handle_command(db, high_chat, f"/play {high_card}")
    assert "error" in bad.lower() or "❌" in bad or "vida" in bad.lower()

    lives = list(db.execute("SELECT lives FROM the_mind_games WHERE game_id = ?", (gid,)))
    assert int(lives[0][0] or 0) < 3


def test_join_denied_when_user_not_in_team(db: Any) -> None:
    _upsert_authorized_user(db, tenant_id="default", user_id="a1", username="host", role="user")
    r = handle_command(db, "111", "/new_mind", requester_id="a1", tenant_id="default")
    gid = _game_id_from_reply(r)
    bad = handle_command(db, "222", f"/join {gid}", requester_id="intruso", tenant_id="default")
    assert "team" in bad.lower() or "Solo" in bad or "autorizado" in bad.lower()


def test_start_mind_requires_two_players_by_default(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DUCKCLAW_THE_MIND_ALLOW_SOLO", raising=False)
    monkeypatch.setattr(
        "duckclaw.forge.skills.the_mind_outbound.send_telegram_dm",
        lambda *a, **k: TelegramDmOutcome.success(),
    )
    r1 = handle_command(db, "111", "/new_mind")
    gid = _game_id_from_reply(r1)
    blocked = handle_command(db, "111", f"/start_mind {gid}")
    assert "2" in blocked or "dos" in blocked.lower() or "join" in blocked.lower()


def test_game_lists_active_games(db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "duckclaw.forge.skills.the_mind_outbound.send_telegram_dm",
        lambda *a, **k: TelegramDmOutcome.success(),
    )
    r_a = handle_command(db, "111", "/new_mind")
    gid_wait = _game_id_from_reply(r_a)
    handle_command(db, "222", f"/join {gid_wait}")
    handle_command(db, "111", f"/start_mind {gid_wait}")
    r_b = handle_command(db, "333", "/new_mind")
    gid_b = _game_id_from_reply(r_b)

    listing = handle_command(db, "111", "/game")
    assert listing
    assert "Partidas activas" in listing or "partidas activas" in listing.lower()
    assert gid_wait.replace("\\_", "_") in listing.replace("\\_", "_") or gid_wait in listing
    assert gid_b.replace("\\_", "_") in listing.replace("\\_", "_") or gid_b in listing
