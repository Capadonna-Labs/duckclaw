"""Tests for duckclaw.api.rate_limit."""

from __future__ import annotations

import asyncio
import os
from unittest import mock

from duckclaw.api.rate_limit import _parse_rate_limit, rate_limit_middleware, _rate_buckets


class TestParseRateLimit:
    def test_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DUCKCLAW_RATE_LIMIT", None)
            assert _parse_rate_limit() == 30

    def test_plain_number(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_RATE_LIMIT": "50"}):
            assert _parse_rate_limit() == 50

    def test_per_minute(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_RATE_LIMIT": "10/minute"}):
            assert _parse_rate_limit() == 10

    def test_invalid_falls_to_default(self) -> None:
        with mock.patch.dict(os.environ, {"DUCKCLAW_RATE_LIMIT": "fast"}):
            assert _parse_rate_limit() == 30


class _FakeClient:
    def __init__(self, host: str = "127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, path: str, method: str = "POST", ip: str = "127.0.0.1"):
        self.url = type("URL", (), {"path": path})()
        self.method = method
        self.client = _FakeClient(ip)
        self.headers: dict[str, str] = {}


class TestRateLimitMiddleware:
    def setup_method(self) -> None:
        _rate_buckets.clear()

    def test_non_chat_path_not_limited(self) -> None:
        async def run() -> None:
            req = _FakeRequest("/api/v1/system/health", method="GET")
            called = False

            async def call_next(_: object) -> str:
                nonlocal called
                called = True
                return "ok"

            await rate_limit_middleware(req, call_next)
            assert called

        asyncio.get_event_loop().run_until_complete(run())

    def test_chat_post_under_limit(self) -> None:
        async def run() -> None:
            with mock.patch.dict(os.environ, {"DUCKCLAW_RATE_LIMIT": "5"}):
                req = _FakeRequest("/api/v1/agent/finanz/chat", method="POST", ip="10.0.0.1")
                called = False

                async def call_next(_: object) -> str:
                    nonlocal called
                    called = True
                    return "ok"

                await rate_limit_middleware(req, call_next)
                assert called

        asyncio.get_event_loop().run_until_complete(run())

    def test_chat_post_over_limit_returns_429(self) -> None:
        async def run() -> None:
            with mock.patch.dict(os.environ, {"DUCKCLAW_RATE_LIMIT": "2"}):
                async def call_next(_: object) -> str:
                    return "ok"

                ip = "10.0.0.99"
                for _ in range(2):
                    req = _FakeRequest("/api/v1/agent/finanz/chat", method="POST", ip=ip)
                    await rate_limit_middleware(req, call_next)

                req = _FakeRequest("/api/v1/agent/finanz/chat", method="POST", ip=ip)
                resp = await rate_limit_middleware(req, call_next)
                assert hasattr(resp, "status_code")
                assert resp.status_code == 429

        asyncio.get_event_loop().run_until_complete(run())
