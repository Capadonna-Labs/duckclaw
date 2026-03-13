"""Load and validate worker manifest.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import os


def _find_templates_root() -> Path:
    """Project root: duckclaw/workers -> project root."""
    here = Path(__file__).resolve().parent
    # duckclaw/workers -> project has templates/ at root
    for parent in (here.parent.parent, here.parent.parent.parent, Path.cwd()):
        d = parent / "templates" / "workers"
        if d.is_dir():
            return parent
    return Path.cwd()


def get_worker_dir(worker_id: str, templates_root: Optional[Path] = None) -> Path:
    """Return templates/workers/<worker_id>/."""
    root = templates_root or _find_templates_root()
    path = root / "templates" / "workers" / worker_id.strip()
    if not path.is_dir():
        raise FileNotFoundError(f"Worker template not found: {path}")
    return path


def load_manifest(worker_id: str, templates_root: Optional[Path] = None) -> WorkerSpec:
    """Load and validate manifest.yaml for a worker. Raises if missing or invalid."""
    worker_dir = get_worker_dir(worker_id, templates_root)
    manifest_path = worker_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.yaml not found in {worker_dir}")

    try:
        import yaml
    except ImportError:
        # Minimal YAML parse for required keys
        raw = manifest_path.read_text(encoding="utf-8")
        data = _minimal_yaml_parse(raw)
    else:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

    if not isinstance(data, dict):
        raise ValueError("manifest.yaml must be a YAML object")

    name = (data.get("name") or data.get("id") or worker_id).strip()
    schema_name = (data.get("schema_name") or data.get("schema") or _default_schema(worker_id)).strip()
    llm = (data.get("llm") or {}).copy() if isinstance(data.get("llm"), dict) else {}
    raw_required = llm.get("required")
    llm_required = (llm.get("model") or "").strip() if raw_required else None
    if raw_required and isinstance(raw_required, str):
        llm_required = raw_required.strip() or llm_required
    temperature = float(llm.get("temperature", 0.2))
    topology = (data.get("topology") or "general").strip().lower()
    skills_list = data.get("skills") or []
    if isinstance(skills_list, str):
        skills_list = [s.strip() for s in skills_list.split(",") if s.strip()]
    # skills: strings (nombres) o dicts (ej. {github: {...}}, {research: {...}}, {tailscale: {...}}, {sft: {...}})
    skills_names = [s for s in skills_list if isinstance(s, str)]
    github_config = None
    research_config = None
    tailscale_config = None
    sft_config = None
    for s in skills_list:
        if isinstance(s, dict):
            if "github" in s and github_config is None:
                github_config = s["github"] if isinstance(s.get("github"), dict) else {}
            if "research" in s and research_config is None:
                research_config = s["research"] if isinstance(s.get("research"), dict) else {}
            if "tailscale" in s and tailscale_config is None:
                tailscale_config = s["tailscale"] if isinstance(s.get("tailscale"), dict) else {}
            if "sft" in s and sft_config is None:
                sft_config = s["sft"] if isinstance(s.get("sft"), dict) else {}
    if github_config is None and isinstance(data.get("github"), dict):
        github_config = data["github"]
    if research_config is None and isinstance(data.get("research"), dict):
        research_config = data["research"]
    if tailscale_config is None and isinstance(data.get("tailscale"), dict):
        tailscale_config = data["tailscale"]
    if sft_config is None and isinstance(data.get("sft"), dict):
        sft_config = data["sft"]
    inference_config = None
    if isinstance(data.get("inference"), dict):
        inference_config = data["inference"]
    homeostasis_config = _load_homeostasis_config(worker_dir, data)
    allowed_tables = data.get("allowed_tables") or []
    if isinstance(allowed_tables, str):
        allowed_tables = [t.strip() for t in allowed_tables.split(",") if t.strip()]
    read_only = bool(data.get("read_only", False))

    return WorkerSpec(
        worker_id=worker_id,
        name=name,
        schema_name=schema_name,
        llm_required=llm_required or None,
        temperature=temperature,
        topology=topology,
        skills_list=skills_names,
        allowed_tables=allowed_tables,
        read_only=read_only,
        worker_dir=worker_dir,
        github_config=github_config,
        research_config=research_config,
        tailscale_config=tailscale_config,
        sft_config=sft_config,
        inference_config=inference_config,
        homeostasis_config=homeostasis_config,
    )


def _load_homeostasis_config(worker_dir: Path, manifest_data: dict) -> Optional[dict]:
    """Load homeostasis config from homeostasis.yaml or manifest homeostasis key."""
    # 1. Try homeostasis.yaml in worker dir
    yaml_path = worker_dir / "homeostasis.yaml"
    if yaml_path.is_file():
        try:
            import yaml
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return data.get("homeostasis") or data
        except Exception:
            pass
    # 2. Fallback to manifest homeostasis key
    h = manifest_data.get("homeostasis")
    if isinstance(h, dict):
        return h
    return None


def _default_schema(worker_id: str) -> str:
    return worker_id.lower().replace("-", "_") + "_worker"


def _minimal_yaml_parse(raw: str) -> dict:
    """Minimal YAML parse for key: value and nested key: value (no arrays)."""
    data: dict = {}
    current_key = None
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if indent == 0:
                data[k] = v
                current_key = k
            elif current_key and indent > 0:
                if current_key not in data or not isinstance(data[current_key], dict):
                    data[current_key] = {}
                data[current_key][k] = v
    return data


class WorkerSpec:
    """Validated worker template specification."""

    __slots__ = (
        "worker_id", "name", "schema_name", "llm_required", "temperature",
        "topology", "skills_list", "allowed_tables", "read_only", "worker_dir",
        "github_config", "research_config", "tailscale_config", "sft_config",
        "inference_config", "homeostasis_config",
    )

    def __init__(
        self,
        worker_id: str,
        name: str,
        schema_name: str,
        llm_required: Optional[str],
        temperature: float,
        topology: str,
        skills_list: list,
        allowed_tables: list,
        read_only: bool,
        worker_dir: Path,
        github_config: Optional[dict] = None,
        research_config: Optional[dict] = None,
        tailscale_config: Optional[dict] = None,
        sft_config: Optional[dict] = None,
        inference_config: Optional[dict] = None,
        homeostasis_config: Optional[dict] = None,
    ):
        self.worker_id = worker_id
        self.name = name
        self.schema_name = schema_name
        self.llm_required = llm_required
        self.temperature = temperature
        self.topology = topology
        self.skills_list = skills_list
        self.allowed_tables = allowed_tables
        self.read_only = read_only
        self.worker_dir = worker_dir
        self.github_config = github_config
        self.research_config = research_config
        self.tailscale_config = tailscale_config
        self.sft_config = sft_config
        self.inference_config = inference_config
        self.homeostasis_config = homeostasis_config
