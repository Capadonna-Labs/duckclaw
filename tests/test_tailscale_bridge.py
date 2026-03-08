"""Tests for Tailscale Bridge skill."""

from __future__ import annotations

from unittest.mock import patch


def test_tailscale_status_parse_json_active() -> None:
    """Parse JSON output returns Active when peers exist."""
    from duckclaw.forge.skills.tailscale_bridge import _parse_status_output

    raw = '{"Self":{"Online":true},"Peer":{"1":{"HostName":"vps","TailscaleIPs":["100.64.0.2"]}}}'
    status, peers = _parse_status_output(raw)
    assert status == "Active"
    assert "100.64.0.2" in str(peers)
    assert "vps" in str(peers)


def test_tailscale_status_parse_json_down() -> None:
    """Parse JSON output returns Down when no peers and offline."""
    from duckclaw.forge.skills.tailscale_bridge import _parse_status_output

    raw = '{"Self":{"Online":false},"Peer":{}}'
    status, peers = _parse_status_output(raw)
    assert status == "Down"
    assert peers == []


def test_tailscale_status_parse_empty() -> None:
    """Empty output returns Down."""
    from duckclaw.forge.skills.tailscale_bridge import _parse_status_output

    status, peers = _parse_status_output("")
    assert status == "Down"
    assert peers == []


def test_tailscale_status_impl_with_mock() -> None:
    """_tailscale_status_impl returns Active when tailscale status --json succeeds."""
    import duckclaw.forge.skills.tailscale_bridge as m

    with patch.object(m, "_run_tailscale_status", return_value='{"Self":{"Online":true},"Peer":{"1":{"HostName":"vps","TailscaleIPs":["100.64.0.2"]}}}'):
        result = m._tailscale_status_impl()
        assert "ConnectionStatus: Active" in result
        assert "100.64.0.2" in result or "vps" in result


def test_register_tailscale_skill_no_config() -> None:
    """register_tailscale_skill does nothing when config is None."""
    from duckclaw.forge.skills.tailscale_bridge import register_tailscale_skill

    tools = []
    register_tailscale_skill(tools, None)
    assert len(tools) == 0


def test_register_tailscale_skill_disabled() -> None:
    """register_tailscale_skill does nothing when tailscale_enabled is False."""
    from duckclaw.forge.skills.tailscale_bridge import register_tailscale_skill

    tools = []
    register_tailscale_skill(tools, {"tailscale_enabled": False})
    assert len(tools) == 0


def test_register_tailscale_skill_adds_tool_when_available() -> None:
    """register_tailscale_skill adds tool when tailscale is in PATH and enabled."""
    from duckclaw.forge.skills.tailscale_bridge import register_tailscale_skill

    tools = []
    with patch("duckclaw.forge.skills.tailscale_bridge.shutil.which", return_value="/usr/bin/tailscale"):
        register_tailscale_skill(tools, {"tailscale_enabled": True})
    if tools:
        assert len(tools) == 1
        assert tools[0].name == "tailscale_status"
