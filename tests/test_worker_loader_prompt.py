"""load_system_prompt: soul.md + system_prompt.md."""

from __future__ import annotations

from pathlib import Path

from duckclaw.workers.loader import append_domain_closure_block, load_system_prompt
from duckclaw.workers.manifest import WorkerSpec


def _spec(worker_dir: Path) -> WorkerSpec:
    return WorkerSpec(
        worker_id="t",
        name="t",
        schema_name="t",
        llm_required=None,
        temperature=0.0,
        topology="general",
        skills_list=[],
        allowed_tables=[],
        read_only=True,
        worker_dir=worker_dir,
    )


def test_load_system_prompt_soul_then_system(tmp_path: Path) -> None:
    d = tmp_path / "w"
    d.mkdir()
    (d / "soul.md").write_text("SOUL_BLOCK", encoding="utf-8")
    (d / "system_prompt.md").write_text("SYS_BLOCK", encoding="utf-8")
    out = load_system_prompt(_spec(d))
    assert out == "SOUL_BLOCK\n\n---\n\nSYS_BLOCK"


def test_load_system_prompt_system_only(tmp_path: Path) -> None:
    d = tmp_path / "w2"
    d.mkdir()
    (d / "system_prompt.md").write_text("ONLY_SYS", encoding="utf-8")
    assert load_system_prompt(_spec(d)) == "ONLY_SYS"


def test_load_system_prompt_default_when_empty(tmp_path: Path) -> None:
    d = tmp_path / "w3"
    d.mkdir()
    default = load_system_prompt(_spec(d))
    assert "asistente" in default.lower()


def test_append_domain_closure_block_appends_when_present(tmp_path: Path) -> None:
    d = tmp_path / "leila"
    d.mkdir()
    (d / "domain_closure.md").write_text("CLOSURE_FINAL", encoding="utf-8")
    out = append_domain_closure_block("BASE", _spec(d))
    assert out == "BASE\n\n---\n\nCLOSURE_FINAL"


def test_append_domain_closure_block_noop_when_missing(tmp_path: Path) -> None:
    d = tmp_path / "no_closure"
    d.mkdir()
    assert append_domain_closure_block("X", _spec(d)) == "X"
