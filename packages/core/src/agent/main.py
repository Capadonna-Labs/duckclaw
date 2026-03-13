"""
Bucle principal del agente soberano IoTCoreLabs.

Usa SlayerConsole para salida visual estándar y DuckClaw para persistencia.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Permitir importar duckclaw cuando se ejecuta desde repo root
if __name__ == "__main__" and (repo_root := Path(__file__).resolve().parent.parent.parent) not in sys.path:
    sys.path.insert(0, str(repo_root))

from duckclaw.utils import SlayerConsole


def run_agent(db_path: str = ":memory:") -> None:
    """Ejecuta el agente con consola forense y DuckClaw."""
    console = SlayerConsole()
    console.print_welcome_banner()

    try:
        import duckclaw
        db = duckclaw.DuckClaw(db_path)
    except ImportError:
        console.print_error("DuckClaw no instalado. Instala con: pip install -e . --no-build-isolation")
        return

    db.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            x DOUBLE, y DOUBLE, z DOUBLE, salud INTEGER, hambre INTEGER
        )
    """)

    # Simular flujo: pensamiento → herramienta → acción DB → sensorium
    console.print_thought(
        "Inicializando estado del agente y comprobando memoria DuckClaw."
    )
    console.print_tool_call("get_environment", {"region": "local", "mode": "sovereign"})
    db.execute("INSERT INTO telemetry VALUES (100.5, 64.0, -200.1, 100, 0)")
    console.print_db_action("INSERT INTO telemetry VALUES (...)", 1)

    console.print_sensorium({"X": 100.5, "Y": 64.0, "Z": -200.1, "Salud": 100, "Hambre": 0})

    console.print_thought("Estado persistido; listo para siguiente ciclo.")
    result = db.query("SELECT * FROM telemetry")
    rows = json.loads(result)
    console.print_db_action("SELECT * FROM telemetry", len(rows))

    # Ejemplo de error (descomentar para probar)
    # console.print_error("Simulación de fallo de recurso.")


if __name__ == "__main__":
    run_agent()
