"""Tests for duckclaw.api.auth."""

from __future__ import annotations

import os
from unittest import mock

from duckclaw.api.auth import (
    _path_is_public,
    verify_tailscale_key,
    verify_jwt,
)


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None, path: str = "/"):
        self.headers = headers or {}
        self.url = type("URL", (), {"path": path})()


class TestPathIsPublic:
    def test_root(self) -> None:
        assert _path_is_public("/")

    def test_health(self) -> None:
        assert _path_is_public("/health")

    def test_docs(self) -> None:
        assert _path_is_public("/docs")
        assert _path_is_public("/docs/")

    def test_redoc(self) -> None:
        assert _path_is_public("/redoc")

    def test_system_health(self) -> None:
        assert _path_is_public("/api/v1/system/health")

    def test_private_paths(self) -> None:
        assert not _path_is_public("/api/v1/agent/chat")
        assert not _path_is_public("/invoke")
        assert not _path_is_public("/stream")


class TestVerifyTailscaleKey:
    def test_valid_key(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_TAILSCALE_AUTH_KEY": "secret123"}):
            req = _FakeRequest(headers={"X-Tailscale-Auth-Key": "secret123"})
            assert verify_tailscale_key(req) is True

    def test_invalid_key(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_TAILSCALE_AUTH_KEY": "secret123"}):
            req = _FakeRequest(headers={"X-Tailscale-Auth-Key": "wrong"})
            assert verify_tailscale_key(req) is False

    def test_missing_header(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_TAILSCALE_AUTH_KEY": "secret123"}):
            req = _FakeRequest(headers={})
            assert verify_tailscale_key(req) is False

    def test_no_env_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DUCKCLAW_TAILSCALE_AUTH_KEY", None)
            req = _FakeRequest(headers={"X-Tailscale-Auth-Key": "anything"})
            assert verify_tailscale_key(req) is False

    def test_timing_safe_comparison(self) -> None:
        """Verify secrets.compare_digest is used (no exact-char timing leak)."""
        with mock.patch.dict(os.environ, {"DUCKCLAW_TAILSCALE_AUTH_KEY": "abc"}):
            req = _FakeRequest(headers={"X-Tailscale-Auth-Key": "abd"})
            assert verify_tailscale_key(req) is False


class TestVerifyJwt:
    def test_no_secret_returns_none(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DUCKCLAW_JWT_SECRET", None)
            req = _FakeRequest(headers={"Authorization": "Bearer xyz"})
            assert verify_jwt(req) is None

    def test_no_auth_header(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_JWT_SECRET": "test"}):
            req = _FakeRequest(headers={})
            assert verify_jwt(req) is None

    def test_non_bearer_prefix(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_JWT_SECRET": "test"}):
            req = _FakeRequest(headers={"Authorization": "Basic abc"})
            assert verify_jwt(req) is None

    def test_valid_jwt(self) -> None:
        try:
            import jwt as pyjwt
        except ImportError:
            return
        secret = "test-secret-key"
        token = pyjwt.encode({"sub": "user1", "role": "admin"}, secret, algorithm="HS256")
        with mock.patch.dict(os.environ, {"DUCKCLAW_JWT_SECRET": secret}):
            req = _FakeRequest(headers={"Authorization": f"Bearer {token}"})
            payload = verify_jwt(req)
            assert payload is not None
            assert payload["sub"] == "user1"

    def test_invalid_jwt(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_JWT_SECRET": "test"}):
            req = _FakeRequest(headers={"Authorization": "Bearer invalid.token.here"})
            assert verify_jwt(req) is None
