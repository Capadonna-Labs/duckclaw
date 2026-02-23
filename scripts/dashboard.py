#!/usr/bin/env python3
"""Dashboard de monitoreo DuckClaw: config del wizard y datos de la base (telegram_messages)."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

CONFIG_KEYS = ("mode", "channel", "bot_mode", "llm_provider", "llm_model", "llm_base_url", "db_path")


def _config_path() -> Path:
    return Path.home() / ".config" / "duckclaw" / "wizard_config.json"


def load_config() -> dict | None:
    path = _config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return {k: data[k] for k in CONFIG_KEYS if k in data and data[k]}
    except Exception:
        return None


def main() -> None:
    st.set_page_config(page_title="DuckClaw Dashboard", layout="wide")
    st.title("DuckClaw — Dashboard de monitoreo")

    config = load_config()
    if not config:
        st.warning(
            "No hay configuración guardada. Ejecuta primero el asistente de instalación:\n\n"
            "```bash\n./scripts/install_duckclaw.sh\n```"
        )
        return

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Configuración (wizard)")
        # No mostrar tokens ni datos sensibles completos
        for key in CONFIG_KEYS:
            val = config.get(key)
            if val is None or val == "":
                continue
            if "token" in key.lower() or key == "channel":
                display = "***" + (str(val)[-4:] if len(str(val)) > 4 else "***")
            else:
                display = str(val)
            st.text(f"{key}: {display}")

    db_path = config.get("db_path")
    if not db_path:
        st.info("No hay ruta de base de datos configurada.")
        return

    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        st.error(f"La base de datos no existe en: {db_path}")
        return

    try:
        from duckclaw import DuckClaw
    except ImportError:
        st.error("No se pudo importar duckclaw. ¿Instalaste el paquete? (pip install -e .)")
        return

    with col2:
        st.subheader("Base de datos")
        st.text(f"Ruta: {db_path}")

    try:
        db = DuckClaw(str(db_path))
    except Exception as e:
        st.error(f"Error al abrir la base de datos: {e}")
        return

    # query() devuelve JSON string; parseamos para listas/dicts
    def _run_query(sql: str) -> list[dict]:
        raw = db.query(sql)
        try:
            return json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return []

    # Tablas
    try:
        tables_result = _run_query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
    except Exception as e:
        st.warning(f"No se pudieron listar tablas: {e}")
        tables_result = []

    if tables_result:
        st.subheader("Tablas")
        st.write(tables_result)

    has_telegram = any(
        (r.get("table_name") if isinstance(r, dict) else getattr(r, "table_name", None)) == "telegram_messages"
        for r in tables_result
    )
    if has_telegram or not tables_result:
        st.subheader("Últimos mensajes (telegram_messages)")
        try:
            limit = st.slider("Número de mensajes", min_value=5, max_value=100, value=20)
            rows = _run_query(
                f"SELECT message_id, chat_id, username, text, received_at FROM telegram_messages "
                f"ORDER BY received_at DESC LIMIT {int(limit)}"
            )
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.caption("Sin mensajes aún.")
        except Exception as e:
            st.caption(f"Tabla telegram_messages no disponible: {e}")

    # Métricas rápidas
    try:
        count_result = _run_query("SELECT COUNT(*) AS n FROM telegram_messages")
        n = count_result[0].get("n", 0) if count_result else 0
        st.metric("Total mensajes en telegram_messages", n)
    except Exception:
        pass


if __name__ == "__main__":
    main()
