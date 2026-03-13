# specs/Sandbox_de_Ejecucion_Libre_Basado_en_Strix.md

"""Strix Sandbox: entorno de ejecución libre aislado con Docker.

- StrixSandboxManager: ciclo de vida del contenedor (provisioning, exec, teardown).
- run_in_sandbox(): bucle de auto-corrección (hasta max_retries intentos).
- data_inject(): exporta SQL de DuckDB a /tmp/.../data.csv para montaje read-only.
- sandbox_tool_factory(): StructuredTool para usar en general_graph.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Imagen base por defecto; sobreescribible con STRIX_SANDBOX_IMAGE
_DEFAULT_IMAGE = "duckclaw/sandbox:latest"
_FALLBACK_IMAGE = "python:3.11-slim"
_SANDBOX_MEMORY = "512m"
_SANDBOX_TIMEOUT = 30          # segundos de timeout por ejecución
_MAX_RETRIES_DEFAULT = 3

# Directorio base de sesiones en el host
_TMP_BASE = Path(tempfile.gettempdir()) / "duckclaw_sandbox"


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    artifacts: list[str] = field(default_factory=list)
    attempts: int = 1

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout[:8000],
            "stderr": self.stderr[:4000],
            "timed_out": self.timed_out,
            "artifacts": self.artifacts,
            "attempts": self.attempts,
        }


def _docker_client():
    """Devuelve docker.DockerClient o levanta ImportError/DockerException."""
    import docker  # noqa: PLC0415
    return docker.from_env()


def _docker_available() -> bool:
    try:
        c = _docker_client()
        c.ping()
        return True
    except Exception:
        return False


def _image_name() -> str:
    return os.environ.get("STRIX_SANDBOX_IMAGE", _DEFAULT_IMAGE)


def _ensure_image(client: Any) -> str:
    """Verifica que la imagen esté disponible; si no, hace pull de fallback."""
    image = _image_name()
    try:
        client.images.get(image)
        return image
    except Exception:
        pass
    # Pull fallback
    try:
        client.images.pull(_FALLBACK_IMAGE)
        return _FALLBACK_IMAGE
    except Exception as e:
        raise RuntimeError(f"No se pudo obtener ninguna imagen Docker para el sandbox: {e}") from e


class StrixSandboxManager:
    """Gestiona el ciclo de vida de contenedores Docker para ejecución aislada.

    Spec: sección 4 y 6 de Sandbox_de_Ejecucion_Libre_Basado_en_Strix.md
    - network_mode=none (Zero exfiltration)
    - --cap-drop=ALL
    - mem_limit=512m
    - Montaje de datos en modo read-only; output en read-write
    """

    def __init__(
        self,
        image: str | None = None,
        timeout: int = _SANDBOX_TIMEOUT,
        memory: str = _SANDBOX_MEMORY,
    ):
        self.image = image or _image_name()
        self.timeout = timeout
        self.memory = memory
        self._containers: dict[str, Any] = {}

    def _session_dirs(self, session_id: str) -> tuple[Path, Path]:
        base = _TMP_BASE / session_id
        data_dir = base / "data"
        out_dir = base / "output"
        data_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        return data_dir, out_dir

    def _get_or_create_container(self, session_id: str, data_dir: Path, out_dir: Path) -> Any:
        import docker  # noqa: PLC0415

        container_name = f"strix_sandbox_{session_id}"
        client = _docker_client()
        image = _ensure_image(client)

        # Reusar si ya está corriendo
        if session_id in self._containers:
            try:
                container = self._containers[session_id]
                container.reload()
                if container.status == "running":
                    return container
            except Exception:
                pass

        # Eliminar contenedor antiguo si existe
        try:
            old = client.containers.get(container_name)
            old.stop(timeout=2)
            old.remove(force=True)
        except docker.errors.NotFound:
            pass
        except Exception:
            pass

        container = client.containers.run(
            image,
            command=["tail", "-f", "/dev/null"],
            name=container_name,
            detach=True,
            mem_limit=self.memory,
            nano_cpus=int(1e9),                  # 1 CPU
            network_mode="none",                  # Zero-Trust: sin red
            cap_drop=["ALL"],                     # Drop de capabilities
            security_opt=["no-new-privileges"],
            volumes={
                str(data_dir.resolve()): {"bind": "/workspace/data", "mode": "ro"},
                str(out_dir.resolve()): {"bind": "/workspace/output", "mode": "rw"},
            },
            working_dir="/workspace",
            environment={"PYTHONUNBUFFERED": "1"},
            remove=False,
        )
        self._containers[session_id] = container
        return container

    def execute(self, session_id: str, code: str, language: str = "python") -> ExecutionResult:
        """Ejecuta código arbitrario en el sandbox del session_id dado.

        Sección 4 de la spec: Execution + Monitoring + Artifact Retrieval.
        """
        data_dir, out_dir = self._session_dirs(session_id)

        try:
            container = self._get_or_create_container(session_id, data_dir, out_dir)
        except Exception as e:
            return ExecutionResult(exit_code=1, stdout="", stderr=f"Error al levantar sandbox: {e}")

        if language == "python":
            # Escribir código en archivo temporal dentro del contenedor
            safe_code = code.replace("\\", "\\\\").replace('"', '\\"')
            cmd = ["python3", "-c", code]
        elif language == "bash":
            cmd = ["bash", "-c", code]
        else:
            return ExecutionResult(exit_code=1, stdout="", stderr=f"Lenguaje no soportado: {language}. Usa python o bash.")

        try:
            exec_result = container.exec_run(
                cmd=cmd,
                workdir="/workspace",
                demux=True,
                environment={"PYTHONPATH": "/workspace"},
            )
            timeout_start = time.perf_counter()
            # demux=True devuelve (stdout_bytes, stderr_bytes)
            raw_stdout, raw_stderr = exec_result.output or (b"", b"")
            stdout = (raw_stdout or b"").decode("utf-8", errors="replace").strip()
            stderr = (raw_stderr or b"").decode("utf-8", errors="replace").strip()
            elapsed = time.perf_counter() - timeout_start
            timed_out = elapsed > self.timeout
        except Exception as e:
            return ExecutionResult(exit_code=1, stdout="", stderr=f"Error de ejecución: {e}")

        artifacts = self._collect_artifacts(out_dir)

        return ExecutionResult(
            exit_code=exec_result.exit_code or 0,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            artifacts=artifacts,
        )

    def _collect_artifacts(self, out_dir: Path) -> list[str]:
        """Mueve artefactos del directorio de salida a la carpeta de plots del proyecto."""
        artifacts = []
        plots_dir = Path("output") / "sandbox"
        plots_dir.mkdir(parents=True, exist_ok=True)
        for f in out_dir.iterdir():
            if f.is_file():
                dest = plots_dir / f.name
                shutil.copy2(f, dest)
                artifacts.append(str(dest.resolve()))
        return artifacts

    def cleanup(self, session_id: str) -> None:
        """Para y elimina el contenedor de una sesión."""
        import docker  # noqa: PLC0415

        container_name = f"strix_sandbox_{session_id}"
        try:
            client = _docker_client()
            container = client.containers.get(container_name)
            container.stop(timeout=3)
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
        except Exception:
            pass
        self._containers.pop(session_id, None)
        # Limpiar directorios temporales
        session_dir = _TMP_BASE / session_id
        shutil.rmtree(session_dir, ignore_errors=True)

    def cleanup_all(self) -> None:
        for sid in list(self._containers.keys()):
            self.cleanup(sid)


# Singleton reutilizable dentro del proceso
_manager: StrixSandboxManager | None = None


def _get_manager() -> StrixSandboxManager:
    global _manager
    if _manager is None:
        _manager = StrixSandboxManager()
    return _manager


def data_inject(db: Any, sql: str, session_id: str) -> str:
    """Exporta el resultado de un SELECT al directorio data/ de la sesión del sandbox.

    Spec (sección 3): firewall de datos — el sandbox solo ve un Parquet/CSV read-only.
    Usa SandboxDataChannel (spec Pipeline_de_Datos_Zero-Copy_con_PyArrow.md):
      - Parquet (columnar, tipado, ≈5× más compacto) cuando PyArrow está disponible.
      - CSV como fallback automático.
    Devuelve la ruta al archivo generado.
    """
    session_dir = _TMP_BASE / session_id
    try:
        from duckclaw.data.arrow_bridge import SandboxDataChannel  # noqa: PLC0415
        return SandboxDataChannel.inject(db, sql, session_dir)
    except ImportError:
        pass
    # Fallback directo si el módulo data no está disponible
    data_dir = session_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / "data.csv"
    try:
        db.execute(f"COPY ({sql}) TO '{dest}' (HEADER, DELIMITER ',')")
        return str(dest)
    except Exception:
        try:
            import csv
            raw = db.query(sql)
            rows = json.loads(raw) if isinstance(raw, str) else (raw or [])
            if not rows:
                return ""
            with open(dest, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            return str(dest)
        except Exception as e:
            return f"Error exportando datos: {e}"


def _correction_prompt(original_request: str, code: str, error: str, attempt: int) -> str:
    return (
        f"El siguiente código Python falló (intento {attempt}).\n\n"
        f"--- CÓDIGO ---\n{code}\n\n"
        f"--- ERROR ---\n{error}\n\n"
        f"--- TAREA ORIGINAL ---\n{original_request}\n\n"
        "Reescribe SOLO el código Python corregido, sin explicaciones, sin markdown, sin triple backtick. "
        "Solo el código puro que se pueda ejecutar directamente con python3 -c."
    )


def run_in_sandbox(
    db: Any,
    llm: Any,
    code: str,
    language: str = "python",
    session_id: str | None = None,
    data_sql: str | None = None,
    original_request: str = "",
    max_retries: int = _MAX_RETRIES_DEFAULT,
    langsmith_tags: list[str] | None = None,
) -> ExecutionResult:
    """Bucle de auto-corrección del spec (sección 5).

    1. Si data_sql -> inyecta CSV en el workspace del sandbox (protocolo de firewall, sección 3).
    2. Ejecuta el código.
    3. Si falla, pide al LLM que corrija y reintenta (max_retries veces).
    4. Registra intención, código y resultado en LangSmith (sección 7).
    """
    if not _docker_available():
        return ExecutionResult(
            exit_code=1,
            stdout="",
            stderr=(
                "Docker no está disponible en este entorno. "
                "Instala y ejecuta Docker para usar el Sandbox de ejecución libre."
            ),
        )

    sid = session_id or uuid.uuid4().hex[:12]
    manager = _get_manager()

    # Protocolo de firewall: inyectar datos si se requiere
    if data_sql:
        data_inject(db, data_sql, sid)

    current_code = code
    result = ExecutionResult(exit_code=1, stdout="", stderr="No ejecutado aún.")
    tags = (langsmith_tags or []) + ["execution_environment:strix_sandbox"]

    for attempt in range(1, max_retries + 1):
        result = manager.execute(sid, current_code, language)
        result.attempts = attempt

        _langsmith_log(
            intent=original_request,
            code=current_code,
            result=result,
            attempt=attempt,
            tags=tags,
        )

        if result.success:
            break

        if attempt < max_retries and llm is not None:
            error_info = result.stderr or result.stdout or "Error desconocido"
            fix_prompt = _correction_prompt(original_request or code, current_code, error_info, attempt)
            try:
                fixed = llm.invoke(fix_prompt)
                fixed_text = (getattr(fixed, "content", None) or str(fixed) or "").strip()
                # Quitar fences de markdown si el modelo los añade
                fixed_text = re.sub(r"^```(?:python)?\s*", "", fixed_text, flags=re.MULTILINE)
                fixed_text = re.sub(r"```\s*$", "", fixed_text, flags=re.MULTILINE).strip()
                if fixed_text:
                    current_code = fixed_text
            except Exception:
                break

    return result


def _langsmith_log(intent: str, code: str, result: ExecutionResult, attempt: int, tags: list[str]) -> None:
    """Trazabilidad forense (sección 7): registra en LangSmith si está configurado."""
    try:
        api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
        if not api_key or os.environ.get("LANGCHAIN_TRACING_V2", "").lower() not in ("true", "1"):
            return
        from langsmith import Client  # noqa: PLC0415
        client = Client(api_key=api_key)
        client.create_run(
            name="strix_sandbox_execution",
            run_type="tool",
            inputs={"intent": intent, "code": code, "attempt": attempt},
            outputs=result.to_dict(),
            tags=tags,
            extra={"metadata": {"execution_environment": "strix_sandbox"}},
        )
    except Exception:
        pass


def sandbox_tool_factory(db: Any, llm: Any) -> Any:
    """Crea el StructuredTool 'run_sandbox' para usar en general_graph.

    Parámetros de entrada para el LLM:
    - code: código Python o Bash a ejecutar
    - language: 'python' (default) o 'bash'
    - data_sql: SQL opcional — el resultado se monta como data.csv dentro del sandbox
    - session_id: identificador de sesión (reutiliza contenedor si ya existe)
    """
    from langchain_core.tools import StructuredTool  # noqa: PLC0415

    def _run(
        code: str,
        language: str = "python",
        data_sql: str = "",
        session_id: str = "",
    ) -> str:
        result = run_in_sandbox(
            db=db,
            llm=llm,
            code=code,
            language=language or "python",
            session_id=session_id or uuid.uuid4().hex[:12],
            data_sql=data_sql or None,
            original_request=code,
        )
        out = {"exit_code": result.exit_code, "output": result.stdout or result.stderr}
        if result.artifacts:
            out["artifacts"] = result.artifacts
        if result.timed_out:
            out["warning"] = "Timeout alcanzado"
        if result.attempts > 1:
            out["auto_corrected_attempts"] = result.attempts
        return json.dumps(out, ensure_ascii=False)

    return StructuredTool.from_function(
        _run,
        name="run_sandbox",
        description=(
            "Ejecuta código Python o Bash en un sandbox Docker aislado (sin acceso a red ni al host). "
            "Usa cuando el usuario pida ejecutar scripts, análisis complejos, modelos, gráficos dinámicos o código libre. "
            "Parámetros: code (str), language ('python'|'bash'), data_sql (SQL para inyectar datos), session_id (str)."
        ),
    )
