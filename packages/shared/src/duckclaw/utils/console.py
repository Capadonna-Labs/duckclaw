"""Rich-based console for sovereign agent observability (IoTCoreLabs)."""

from __future__ import annotations

import json
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import DOUBLE


class SlayerConsole:
    """Consola estándar para observabilidad forense de agentes con DuckClaw."""

    def __init__(self, console: Optional[Console] = None) -> None:
        self._console = console or Console()

    def print_thought(self, thought: str) -> None:
        """Panel cian en itálica con título '🧠 Thought'."""
        text = Text(thought, style="italic cyan")
        self._console.print(
            Panel(
                text,
                title="[bold cyan]🧠 Thought[/]",
                border_style="cyan",
            )
        )

    def print_thought_stream(self, chunks: list[str] | None = None) -> None:
        """Streaming de pensamiento: imprime chunks seguidos y cierra con panel.
        Si se pasa una lista, se imprime fluido; luego se puede llamar a print_thought
        con el texto completo para el panel."""
        if not chunks:
            return
        for chunk in chunks[:-1]:
            self._console.print(Text(chunk, style="italic cyan"), end="")
        if chunks:
            self._console.print(Text(chunks[-1], style="italic cyan"))

    def print_tool_call(self, name: str, args: dict[str, Any]) -> None:
        """Tabla amarilla con el nombre de la herramienta y sus argumentos en JSON."""
        table = Table(show_header=True, header_style="bold yellow", border_style="yellow")
        table.add_column("Tool", style="yellow")
        table.add_column("Arguments (JSON)", style="yellow")
        table.add_row(name, json.dumps(args, ensure_ascii=False, indent=2))
        self._console.print(table)

    def print_db_action(self, query: str, count: int) -> None:
        """Mensaje magenta para DuckClaw SQL indicando filas afectadas."""
        self._console.print(
            f"[magenta]DuckClaw[/] [dim]→[/] [magenta]{query}[/] [dim]({count} row(s))[/]"
        )

    def print_sensorium(self, data: dict[str, Any]) -> None:
        """Línea blanca tenue (dim) con el estado vital (X, Y, Z, Salud, Hambre)."""
        x = data.get("X", data.get("x", "—"))
        y = data.get("Y", data.get("y", "—"))
        z = data.get("Z", data.get("z", "—"))
        salud = data.get("Salud", data.get("salud", "—"))
        hambre = data.get("Hambre", data.get("hambre", "—"))
        line = f"  [dim white]X={x}  Y={y}  Z={z}  Salud={salud}  Hambre={hambre}[/]"
        self._console.print(line)

    def print_error(self, message: str) -> None:
        """Panel rojo con título '❌ Error'."""
        self._console.print(
            Panel(
                message,
                title="[bold red]❌ Error[/]",
                border_style="red",
            )
        )

    def print_welcome_banner(self) -> None:
        """Banner de bienvenida IoTCoreLabs con borde doble y color verde."""
        self._console.print(
            Panel(
                "[bold green]DuckClaw 🦆⚔️[/]",
                border_style="green",
                box=DOUBLE,
            )
        )
