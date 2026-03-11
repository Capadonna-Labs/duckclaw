"""
AgentAssembler: único punto de instanciación de agentes LangGraph.

Lee especificaciones YAML y produce grafos compilados listos para usar.
Delega a build_general_graph, build_retail_graph, build_entry_router_graph
y a la lógica de WorkerFactory para workers.

Spec: Agent Forge Refactor
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


class AgentAssembler:
    """Ensambla un LangGraph compilado desde una especificación YAML."""

    def __init__(self, spec: dict, templates_root: Optional[Path] = None, source_path: Optional[Path] = None):
        self.spec = spec
        self._troot = templates_root
        self._source_path = source_path

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        templates_root: Optional[Path] = None,
    ) -> "AgentAssembler":
        """Carga la especificación desde un archivo YAML."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"YAML no encontrado: {path}")

        if yaml is None:
            raise ImportError("Instala PyYAML: pip install pyyaml")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"El YAML debe ser un objeto: {path}")

        # Inferir type para manifests de workers (templates/workers/*/manifest.yaml)
        if "type" not in data:
            if "schema_name" in data or "skills" in data:
                data["type"] = "worker"
            else:
                data["type"] = "general"

        # Inferir worker id desde path: templates/workers/<id>/manifest.yaml
        if data.get("type") == "worker" and not (data.get("id") or data.get("worker_id")):
            parts = path.parts
            if "workers" in parts:
                idx = parts.index("workers")
                if idx + 1 < len(parts):
                    data["id"] = parts[idx + 1]

        troot = templates_root
        if troot is None and "workers" in str(path):
            parts = path.parts
            if "workers" in parts:
                idx = parts.index("workers")
                # templates_root = project root (parent of templates/). Need idx >= 1
                # so we have at least one parent before "workers"; else fallback.
                if idx >= 1:
                    troot = Path(*path.parts[: idx - 1])
        if troot is None:
            troot = Path(__file__).resolve().parent.parent.parent

        return cls(data, templates_root=troot, source_path=path)

    def build(
        self,
        *,
        db: Optional[Any] = None,
        llm: Optional[Any] = None,
        store_db: Optional[Any] = None,
        console: Optional[Any] = None,
        save_traces: bool = False,
        send_to_langsmith: bool = False,
        **overrides,
    ) -> Any:
        """Construye y retorna el LangGraph compilado según el tipo de spec. Para workers, db/llm pueden ser None si db_path está en overrides."""
        t = (self.spec.get("type") or "general").strip().lower()
        if t == "general":
            return self._build_general(db, llm, **overrides)
        if t == "retail":
            return self._build_retail(store_db or db, llm, console=console, **overrides)
        if t == "entry_router":
            return self._build_router(
                db,
                llm,
                store_db=store_db,
                console=console,
                save_traces=save_traces,
                send_to_langsmith=send_to_langsmith,
                **overrides,
            )
        if t == "worker":
            return self._build_worker(db, llm, **overrides)
        raise ValueError(f"Tipo de agente desconocido: {t!r}")

    def _build_general(self, db: Any, llm: Any, **overrides) -> Any:
        """Construye el grafo general (SQL, schema, memory, sandbox)."""
        from duckclaw.agents.general_graph import build_general_graph

        system_prompt = overrides.get("system_prompt") or self.spec.get("system_prompt") or ""
        tools_spec = overrides.get("tools_spec") or self.spec.get("tools") or None
        return build_general_graph(
            db,
            llm,
            system_prompt=system_prompt,
            tools_spec=tools_spec,
        )

    def _build_retail(
        self,
        store_db: Any,
        llm: Any,
        console: Optional[Any] = None,
        **overrides,
    ) -> Any:
        """Construye el grafo retail (Contador Soberano)."""
        from duckclaw.agents.retail_graph import build_retail_graph

        system_prompt = overrides.get("system_prompt") or self.spec.get("system_prompt") or ""
        return build_retail_graph(
            store_db,
            llm,
            console=console,
            system_prompt=system_prompt,
        )

    def _build_router(
        self,
        db: Any,
        llm: Any,
        *,
        store_db: Optional[Any] = None,
        console: Optional[Any] = None,
        save_traces: bool = False,
        send_to_langsmith: bool = False,
        **overrides,
    ) -> Any:
        """Construye el grafo entry_router (ruteo retail/general)."""
        from duckclaw.agents.router import build_entry_router_graph

        system_prompt = overrides.get("system_prompt") or self.spec.get("system_prompt") or ""
        llm_provider = overrides.get("llm_provider") or ""
        llm_model = overrides.get("llm_model") or ""
        return build_entry_router_graph(
            db,
            llm,
            store_db=store_db,
            console=console,
            system_prompt=system_prompt,
            llm_provider=llm_provider,
            llm_model=llm_model,
            save_traces=save_traces,
            send_to_langsmith=send_to_langsmith,
        )

    def _build_worker(self, db: Any, llm: Any, **overrides) -> Any:
        """Construye el grafo de un worker (template-based)."""
        from duckclaw.workers.factory import build_worker_graph

        worker_id = self.spec.get("id") or self.spec.get("worker_id") or ""
        if not worker_id:
            raise ValueError("Worker spec debe tener 'id' o 'worker_id'")

        db_path = overrides.get("db_path")
        if db_path is None and db is not None:
            db_path = getattr(db, "_path", None) or getattr(db, "path", None)
        if db_path is None or (isinstance(db_path, str) and not db_path.strip()):
            from duckclaw.gateway_db import get_gateway_db_path
            db_path = get_gateway_db_path()

        troot = self._troot
        if troot is None:
            troot = Path(__file__).resolve().parent.parent.parent

        return build_worker_graph(
            worker_id,
            db_path,
            llm,
            templates_root=troot,
            instance_name=overrides.get("instance_name"),
            llm_provider=overrides.get("llm_provider"),
            llm_model=overrides.get("llm_model"),
            llm_base_url=overrides.get("llm_base_url"),
        )
