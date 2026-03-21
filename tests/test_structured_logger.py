"""Smoke tests for Observabilidad 2.0 structured logging."""

from __future__ import annotations

import logging


def test_duckclaw_log_filter_injects_context() -> None:
    from duckclaw.utils.logger import (
        DuckClawLogFilter,
        DuckClawStructuredFormatter,
        ctx_chat,
        ctx_tenant,
        ctx_worker,
        reset_log_context,
        set_log_context,
    )

    reset_log_context()
    set_log_context(tenant_id="acme", worker_id="finanz", chat_id="12345")
    fmt = DuckClawStructuredFormatter()
    flt = DuckClawLogFilter()
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    assert flt.filter(record) is True
    line = fmt.format(record)
    assert "acme" in line and "finanz" in line and "12345" in line and "hello" in line
    reset_log_context()


def test_extract_usage_from_messages_empty() -> None:
    from duckclaw.utils.logger import extract_usage_from_messages

    assert extract_usage_from_messages(None) is None
    assert extract_usage_from_messages([]) is None


def test_log_tool_execution_sync_timing() -> None:
    from duckclaw.utils.logger import log_tool_execution_sync

    @log_tool_execution_sync(name="dummy_tool")
    def _f(x: int) -> int:
        return x + 1

    assert _f(1) == 2


