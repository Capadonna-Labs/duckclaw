"""
Tests para el pipeline Singleton Writer Bridge (API Gateway → Redis → DB Writer → DuckDB).

Incluye:
- Tests unitarios con mocks (payload, health check, gateway endpoint).
- Test de integración opcional (marcado para ejecución explícita si Redis está disponible).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Raíz del monorepo (tests/ está en la raíz)
REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES = REPO_ROOT / "services"
DB_WRITER_DIR = SERVICES / "db-writer"
API_GATEWAY_DIR = SERVICES / "api-gateway"
GATEWAY_URL = "http://127.0.0.1:8000"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


# ─── Funciones del pipeline (reutilizadas por tests de integración y unitarios) ─────────────────

def ensure_redis() -> bool:
    """Comprueba que Redis esté accesible; opcionalmente lo levanta con Docker."""
    try:
        import redis
        r = redis.from_url(REDIS_URL, socket_connect_timeout=2)
        r.ping()
        r.close()
        print("[pipeline] Redis ya está accesible en", REDIS_URL)
        return True
    except Exception:
        try:
            subprocess.run(
                ["docker", "run", "-d", "--name", "duckclaw-redis", "-p", "6379:6379", "redis:7-alpine"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            print("[pipeline] Contenedor docker 'duckclaw-redis' creado, esperando a que Redis arranque...")
            time.sleep(2)
            import redis
            r = redis.from_url(REDIS_URL, socket_connect_timeout=5)
            r.ping()
            r.close()
            print("[pipeline] Redis accesible tras levantar contenedor docker-redis.")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("[pipeline] No se pudo levantar Redis automáticamente (Docker ausente o fallo en 'docker run').")
            return False


def start_db_writer():
    """Arranca el DB Writer en segundo plano."""
    if not (DB_WRITER_DIR / "main.py").exists():
        return None
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DB_WRITER_DIR)
    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=DB_WRITER_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print("[pipeline] DB Writer iniciado en segundo plano (services/db-writer/main.py).")
    return proc


def start_api_gateway():
    """Arranca el API Gateway con uvicorn en segundo plano."""
    if not (API_GATEWAY_DIR / "main.py").exists():
        return None
    env = os.environ.copy()
    env["PYTHONPATH"] = str(API_GATEWAY_DIR)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=API_GATEWAY_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print("[pipeline] API Gateway iniciado en segundo plano en http://127.0.0.1:8000.")
    return proc


def wait_health(url: str, timeout: float = 15.0) -> bool:
    """Espera a que el endpoint /health responda."""
    import urllib.request
    health_url = f"{url.rstrip('/')}/health"
    deadline = time.monotonic() + timeout
    print(f"[pipeline] Esperando a que {health_url} devuelva 200 (timeout {timeout}s)...")
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as r:
                if r.status == 200:
                    print("[pipeline] /health OK (status=200).")
                    return True
        except Exception:
            time.sleep(0.5)
    print("[pipeline] /health no respondió 200 dentro del timeout.")
    return False


def post_write() -> bool:
    """Envía POSTs de prueba a /api/v1/db/write (CREATE TABLE + INSERT)."""
    import urllib.request
    bodies = [
        {"query": "CREATE TABLE IF NOT EXISTS _pipeline_test (id INTEGER, msg VARCHAR)", "params": [], "tenant_id": "default"},
        {"query": "INSERT INTO _pipeline_test (id, msg) VALUES (?, ?)", "params": [1, "Singleton Writer Bridge OK"], "tenant_id": "default"},
    ]
    print("[pipeline] Enviando escrituras de prueba al Gateway...")
    for idx, body in enumerate(bodies, start=1):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{GATEWAY_URL}/api/v1/db/write",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status not in (200, 202):
                print(f"[pipeline] Solicitud {idx} a /api/v1/db/write falló con status={r.status}.")
                return False
            else:
                print(f"[pipeline] Solicitud {idx} a /api/v1/db/write aceptada (status={r.status}).")
    print("[pipeline] Todas las solicitudes de escritura de prueba fueron aceptadas por el Gateway.")
    return True


# ─── Payload y helpers reutilizables (misma forma que el pipeline) ─────────────────────────────

def _build_write_payload(query: str, params: list, tenant_id: str = "default") -> dict:
    """Construye el body que enviaría el script al Gateway (sin task_id; el Gateway lo añade)."""
    return {"query": query, "params": params, "tenant_id": tenant_id}


# ─── Unit tests ────────────────────────────────────────────────────────────────────────────────

def test_write_request_payload_has_required_fields() -> None:
    """El payload de escritura debe tener query, params y tenant_id."""
    payload = _build_write_payload("INSERT INTO t (id) VALUES (?)", [1], "default")
    assert "query" in payload
    assert "params" in payload
    assert "tenant_id" in payload
    assert payload["query"] == "INSERT INTO t (id) VALUES (?)"
    assert payload["params"] == [1]
    assert payload["tenant_id"] == "default"


def test_pipeline_test_payloads_match_gateway_contract() -> None:
    """Los dos payloads del pipeline (CREATE TABLE + INSERT) cumplen el contrato del Gateway."""
    create = _build_write_payload(
        "CREATE TABLE IF NOT EXISTS _pipeline_test (id INTEGER, msg VARCHAR)",
        [],
    )
    insert = _build_write_payload(
        "INSERT INTO _pipeline_test (id, msg) VALUES (?, ?)",
        [1, "Singleton Writer Bridge OK"],
    )
    for p in (create, insert):
        assert isinstance(p["query"], str) and len(p["query"]) > 0
        assert isinstance(p["params"], list)
        assert isinstance(p["tenant_id"], str)
    assert not create["query"].strip().upper().startswith("SELECT")
    assert not insert["query"].strip().upper().startswith("SELECT")


def test_wait_health_returns_true_when_server_returns_200() -> None:
    """wait_health debe devolver True si el servidor responde 200."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = wait_health("http://fake:8000", timeout=0.5)
    assert result is True


def test_ensure_redis_returns_false_when_connection_fails() -> None:
    """ensure_redis debe devolver False si Redis no está disponible y Docker no puede arrancarlo."""
    with patch("redis.from_url") as mock_from_url:
        mock_from_url.return_value.ping.side_effect = OSError("Connection refused")
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            result = ensure_redis()
    assert result is False


# ─── Tests del API Gateway (FastAPI TestClient con Redis mockeado) ───────────────────────────

@pytest.fixture
def gateway_app():
    """App FastAPI del Gateway con Redis mockeado (para no depender de Redis real)."""
    sys.path.insert(0, str(API_GATEWAY_DIR))
    try:
        with patch("redis.asyncio.Redis.from_url") as mock_from_url:
            mock_conn = MagicMock()
            mock_conn.lpush = AsyncMock(return_value=1)
            mock_conn.aclose = AsyncMock(return_value=None)
            mock_from_url.return_value = mock_conn
            import main as gateway_main
            yield gateway_main.app
    finally:
        if str(API_GATEWAY_DIR) in sys.path:
            sys.path.remove(str(API_GATEWAY_DIR))


def test_gateway_health_returns_ok(gateway_app) -> None:
    """GET /health debe devolver 200 y status ok."""
    from fastapi.testclient import TestClient
    with TestClient(gateway_app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
    assert "service" in r.json()


def test_gateway_rejects_select_queries(gateway_app) -> None:
    """POST /api/v1/db/write con query SELECT debe devolver 400."""
    from fastapi.testclient import TestClient
    with TestClient(gateway_app) as client:
        r = client.post(
            "/api/v1/db/write",
            json=_build_write_payload("SELECT 1", []),
        )
    assert r.status_code == 400
    assert "SELECT" in (r.json().get("detail") or "")


def test_gateway_accepts_insert_returns_202_and_task_id(gateway_app) -> None:
    """POST /api/v1/db/write con INSERT debe devolver 202 y task_id."""
    from fastapi.testclient import TestClient
    with TestClient(gateway_app) as client:
        r = client.post(
            "/api/v1/db/write",
            json=_build_write_payload("INSERT INTO t (id) VALUES (?)", [1]),
        )
    assert r.status_code == 202
    data = r.json()
    assert data.get("status") == "enqueued"
    assert "task_id" in data
    assert len(data["task_id"]) > 0


def test_gateway_accepts_create_table_returns_202(gateway_app) -> None:
    """POST /api/v1/db/write con CREATE TABLE debe devolver 202."""
    from fastapi.testclient import TestClient
    with TestClient(gateway_app) as client:
        r = client.post(
            "/api/v1/db/write",
            json=_build_write_payload(
                "CREATE TABLE IF NOT EXISTS _test (id INTEGER)",
                [],
            ),
        )
    assert r.status_code == 202
    assert r.json().get("status") == "enqueued"


# ─── Test de integración (requiere Redis y servicios; marcar para ejecución opcional) ────────

@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_SINGLETON_PIPELINE_INTEGRATION") != "1",
    reason="Set RUN_SINGLETON_PIPELINE_INTEGRATION=1 to run full pipeline (Redis + DB Writer + Gateway)",
)
def test_full_pipeline_e2e() -> None:
    """
    Ejecuta el flujo completo: Redis, DB Writer, Gateway, POST y verificación.
    Solo se ejecuta si RUN_SINGLETON_PIPELINE_INTEGRATION=1.
    """
    os.chdir(REPO_ROOT)
    assert ensure_redis(), "Redis must be running (e.g. docker run -d -p 6379:6379 redis:7-alpine)"
    (REPO_ROOT / "db").mkdir(parents=True, exist_ok=True)
    db_writer_proc = start_db_writer()
    assert db_writer_proc is not None
    gateway_proc = start_api_gateway()
    assert gateway_proc is not None
    try:
        assert wait_health(GATEWAY_URL, timeout=15.0), "Gateway /health did not respond"
        assert post_write(), "POST /api/v1/db/write failed"
        time.sleep(3)
    finally:
        gateway_proc.terminate()
        db_writer_proc.terminate()
        gateway_proc.wait(timeout=5)
        db_writer_proc.wait(timeout=5)