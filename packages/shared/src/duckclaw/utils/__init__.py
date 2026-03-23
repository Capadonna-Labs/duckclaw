"""DuckClaw shared utilities."""

from duckclaw.utils.langsmith_trace import (
    create_completed_langsmith_run,
    get_tracing_config,
    run_name_for_langsmith,
)
from duckclaw.utils.logger import (
    configure_structured_logging,
    extract_usage_from_messages,
    format_chat_id_for_terminal,
    get_obs_logger,
    log_err,
    log_plan,
    log_req,
    log_res,
    log_sys,
    log_tool_execution_async,
    log_tool_execution_sync,
    log_tool_msg,
    reset_log_context,
    set_log_context,
    structured_log_context,
)

__all__ = [
    "configure_structured_logging",
    "extract_usage_from_messages",
    "format_chat_id_for_terminal",
    "create_completed_langsmith_run",
    "get_tracing_config",
    "run_name_for_langsmith",
    "get_obs_logger",
    "log_err",
    "log_plan",
    "log_req",
    "log_res",
    "log_sys",
    "log_tool_execution_async",
    "log_tool_execution_sync",
    "log_tool_msg",
    "reset_log_context",
    "set_log_context",
    "structured_log_context",
]
