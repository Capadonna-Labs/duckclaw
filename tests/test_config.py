"""Tests for duckclaw.utils.config."""

import os
from unittest import mock

from duckclaw.utils.config import parse_bool, resolve_display_model


class TestParseBool:
    def test_truthy_values(self) -> None:
        for v in ("true", "True", "TRUE", "1", "yes", "Yes", "y", "Y", "sí", "si"):
            assert parse_bool(v), f"Expected True for {v!r}"

    def test_falsy_values(self) -> None:
        for v in ("false", "False", "0", "no", "No", "", "random"):
            assert not parse_bool(v), f"Expected False for {v!r}"

    def test_non_string(self) -> None:
        assert parse_bool(True)
        assert not parse_bool(False)
        assert not parse_bool(None)
        assert parse_bool(1)
        assert not parse_bool(0)


class TestResolveDisplayModel:
    def test_explicit_provider_model(self) -> None:
        assert resolve_display_model("openai", "gpt-4o") == "openai:gpt-4o"

    def test_provider_only(self) -> None:
        assert resolve_display_model("deepseek", "") == "deepseek"

    def test_none_llm(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DUCKCLAW_LLM_PROVIDER", None)
            os.environ.pop("DUCKCLAW_LLM_MODEL", None)
            assert resolve_display_model("", "") == "none_llm"

    def test_mlx_with_model_id(self) -> None:
        with mock.patch.dict(os.environ, {"MLX_MODEL_ID": "/models/Slayer-8B-V1.1"}):
            result = resolve_display_model("mlx", "")
            assert result == "mlx:Slayer-8B-V1.1"

    def test_mlx_with_model_path(self) -> None:
        env = {"MLX_MODEL_PATH": "/path/to/Navigator-3B"}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("MLX_MODEL_ID", None)
            result = resolve_display_model("mlx", "")
            assert result == "mlx:Navigator-3B"

    def test_mlx_no_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MLX_MODEL_ID", None)
            os.environ.pop("MLX_MODEL_PATH", None)
            assert resolve_display_model("mlx", "") == "mlx:local"
