"""
Entry point for a hired worker process (PM2).

Usage:
  python -m duckclaw.workers.run_worker finanz --instance FinanzBot
  (env: DUCKCLAW_WORKER_ID, DUCKCLAW_WORKER_INSTANCE, DUCKCLAW_DB_PATH, etc.)

Starts a minimal HTTP server that invokes the worker graph on POST /invoke.
LangSmith: tag with worker_role and instance from env.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Load .env.<instance> if present
def _load_env():
    instance = os.environ.get("DUCKCLAW_WORKER_INSTANCE", "").strip()
    if instance:
        for base in (Path.cwd(), Path(__file__).resolve().parent.parent.parent):
            env_file = base / f".env.{instance}"
            if env_file.is_file():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip("'\"").strip()
                    if k:
                        os.environ.setdefault(k, v)
                break
_load_env()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("worker_id", nargs="?", default="", help="Worker template id (e.g. finanz)")
    parser.add_argument("--instance", default="", help="Instance name (PM2 app name)")
    parser.add_argument("--port", type=int, default=0, help="Port (default from WORKER_PORT or 8124)")
    args = parser.parse_args()
    if args.worker_id:
        os.environ["DUCKCLAW_WORKER_ID"] = args.worker_id
    if args.instance:
        os.environ["DUCKCLAW_WORKER_INSTANCE"] = args.instance
    if args.port:
        os.environ["WORKER_PORT"] = str(args.port)

    WORKER_ID = os.environ.get("DUCKCLAW_WORKER_ID", "").strip()
    INSTANCE = os.environ.get("DUCKCLAW_WORKER_INSTANCE", "").strip()
    if not WORKER_ID:
        print("DUCKCLAW_WORKER_ID is required", file=sys.stderr)
        sys.exit(1)

    from duckclaw.forge import AgentAssembler, WORKERS_TEMPLATES_DIR

    yaml_path = WORKERS_TEMPLATES_DIR / WORKER_ID / "manifest.yaml"
    graph = AgentAssembler.from_yaml(yaml_path).build(
        db=None,
        llm=None,
        db_path=os.environ.get("DUCKCLAW_DB_PATH"),
        instance_name=INSTANCE or None,
    )

    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
        import uvicorn
    except ImportError:
        print("Install: uv sync --extra serve", file=sys.stderr)
        sys.exit(1)

    app = FastAPI(title=f"Worker {WORKER_ID}", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    class InvokeBody(BaseModel):
        message: str = ""
        history: list = []
        thread_id: str = ""

    @app.post("/invoke")
    def invoke(body: InvokeBody):
        state = {"incoming": body.message, "history": body.history or []}
        result = graph.invoke(state)
        reply = result.get("reply") or ""
        return {"reply": reply, "worker_id": WORKER_ID, "instance": INSTANCE}

    @app.get("/health")
    def health():
        return {"status": "ok", "worker_id": WORKER_ID, "instance": INSTANCE}

    port = args.port or int(os.environ.get("WORKER_PORT", "8124"))
    print(f"Worker {WORKER_ID} ({INSTANCE or 'default'}) → http://0.0.0.0:{port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
