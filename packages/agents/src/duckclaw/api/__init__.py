# duckclaw.api — alias para la app del API Gateway (services/api-gateway/main.py).
# Permite arrancar con: uvicorn duckclaw.api:app (p. ej. desde PM2 con config antiguo).

from pathlib import Path
import sys

_repo_root = Path(__file__).resolve().parents[5]
_gateway_dir = _repo_root / "services" / "api-gateway"
if _gateway_dir.is_dir() and str(_gateway_dir) not in sys.path:
    sys.path.insert(0, str(_gateway_dir))

import main as _gateway_main  # noqa: E402

app = _gateway_main.app
