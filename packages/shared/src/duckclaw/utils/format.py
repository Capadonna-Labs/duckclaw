"""Formateo de respuestas de herramientas para mostrar al usuario."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path


def _escape_html(text: str) -> str:
    """Escapa caracteres para Telegram HTML (parse_mode='HTML')."""
    return html.escape(text, quote=False)


def _truncate_at_break(text: str, max_len: int = 600) -> str:
    """Trunca en un límite de frase o párrafo para evitar cortes bruscos con '...'."""
    if not text or len(text) <= max_len:
        return text
    s = text[: max_len + 1]
    for sep in ("\n\n", ".\n", "\n", ". ", " "):
        idx = s.rfind(sep)
        if idx > max_len // 2:
            return text[: idx + len(sep)].strip()
    return text[:max_len].strip()


def format_for_telegram(text: str, max_len: int = 800) -> str:
    """
    Convierte la respuesta BI/markdown a formato Telegram con emojis y HTML.
    Usar con message.reply_text(..., parse_mode='HTML').
    max_len: truncar a este tamaño (default 800 para captions; usar 3500 para mensajes de texto).
    """
    if not text or not text.strip():
        return ""
    s = text.strip()
    out: list[str] = []
    lines = s.split("\n")
    is_first_content = True
    for i, line in enumerate(lines):
        stripped = line.strip()
        # ## Header → emoji + bold
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            out.append(f"📌 <b>{_escape_html(title)}</b>")
            is_first_content = False
            continue
        # ### Subheader
        if stripped.startswith("### "):
            title = stripped[4:].strip()
            out.append(f"▸ <b>{_escape_html(title)}</b>")
            is_first_content = False
            continue
        # **bold** → <b>bold</b>
        if "**" in stripped:
            parts = re.split(r"\*\*", stripped)
            res = ""
            for j, p in enumerate(parts):
                if j % 2 == 1:
                    res += f"<b>{_escape_html(p)}</b>"
                else:
                    res += _escape_html(p)
            out.append(res)
            is_first_content = False
            continue
        # Lista numerada 1. 2. 3.
        m = re.match(r"^(\d+)\.\s+(.+)", stripped)
        if m:
            num = int(m.group(1))
            content = m.group(2)
            emoji = "🥇" if num == 1 else "🥈" if num == 2 else "🥉" if num == 3 else "•"
            out.append(f"{emoji} {_escape_html(content)}")
            is_first_content = False
            continue
        # Línea vacía
        if not stripped:
            out.append("")
            continue
        # Primera línea con contenido: añadir emoji según contexto
        if is_first_content:
            if re.match(r"^Hay \d+ tablas?", stripped, re.I) or "tablas" in stripped.lower() and ("son:" in stripped.lower() or "son " in stripped.lower()):
                out.append(f"📊 {_escape_html(stripped)}")
            elif "mejores vendedores" in stripped.lower() or "vendedores:" in stripped.lower():
                out.append(f"🏆 {_escape_html(stripped)}")
            elif "tiempo de entrega" in stripped.lower() or "promedio" in stripped.lower():
                out.append(f"📦 {_escape_html(stripped)}")
            elif "casos críticos" in stripped.lower():
                out.append(f"⚠️ {_escape_html(stripped)}")
            elif "clientes" in stripped.lower() and ("top" in stripped.lower() or "ventas" in stripped.lower() or "fidelizar" in stripped.lower()):
                out.append(f"👥 {_escape_html(stripped)}")
            elif "ventas por categoría" in stripped.lower():
                out.append(f"📈 {_escape_html(stripped)}")
            elif "satisfacción" in stripped.lower() or "reviews" in stripped.lower():
                out.append(f"⭐ {_escape_html(stripped)}")
            elif "resumen" in stripped.lower():
                out.append(f"📋 {_escape_html(stripped)}")
            else:
                out.append(_escape_html(stripped))
            is_first_content = False
        else:
            out.append(_escape_html(stripped))
    result = "\n".join(out)
    if len(result) > max_len:
        result = _truncate_at_break(result, max_len)
    return result


def strip_paths_from_reply(text: str) -> str:
    """Quita avisos de guardado y rutas; devuelve el resto sin truncar."""
    if not text or not text.strip():
        return text or ""
    s = re.sub(r"\s*[.;]?\s*(?:El gráfico|La gráfica|El diagrama|La imagen)\s+(?:ha\s+sido\s+)?guardad[oa]\s+en:\s*[^\n]+", "", text, flags=re.IGNORECASE)
    s = re.sub(r"\s*[.;]?\s*El archivo\s+se\s+ha\s+guardado\s+en:\s*[^\n]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[.;]?\s*Archivo\s+Excel\s+guardado:\s*[^\n]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[.;]?\s*Archivo\s+Markdown\s+guardado:\s*[^\n]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[.;]?\s*Archivo\s+guardado:\s*[^\n]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[.;]?\s*(?:guardado|guardada)\s+en:\s*[^\n]+", "", s, flags=re.IGNORECASE)
    lines = s.split("\n")
    out = []
    path_kw = ("guardado en", "guardada en", "se ha guardado", "archivo se ha guardado", "saved in", "saved to", "ruta:", "path:")
    for line in lines:
        low = line.strip().lower()
        if any(k in low for k in path_kw):
            continue
        if any(ext in low for ext in (".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".md")) and ("/" in line or "\\" in line):
            continue
        out.append(line)
    return re.sub(r"\s{2,}", " ", "\n".join(out).strip()).strip()


def caption_for_photo(text: str, image_paths: list[str]) -> str:
    """
    Quita del texto avisos de guardado y rutas. Devuelve solo insights para caption en Telegram.
    """
    if not text or not text.strip():
        return ""
    # Quitar avisos de guardado y rutas (inline, hasta fin de línea)
    text = re.sub(
        r"\s*[.;]?\s*(?:El gráfico|La gráfica|El diagrama|La imagen)\s+(?:ha\s+sido\s+)?guardad[oa]\s+en:\s*[^\n]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*[.;]?\s*El archivo\s+se\s+ha\s+guardado\s+en:\s*[^\n]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*[.;]?\s*(?:guardado|guardada)\s+en:\s*[^\n]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    lines = text.split("\n")
    out: list[str] = []
    path_keywords = ("guardado en", "guardada en", "se ha guardado", "archivo se ha guardado", "saved in", "saved to", "encontrado en", "archivo en", "ruta:", "path:")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        lower = stripped.lower()
        if any(kw in lower for kw in path_keywords):
            continue
        if any(ext in lower for ext in (".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".md")) and ("/" in stripped or "\\" in stripped):
            continue
        out.append(line)
    result = re.sub(r"\s{2,}", " ", "\n".join(out).strip())
    if len(result) > 600:
        result = _truncate_at_break(result, 600)
    return result.strip()


# Nombres de archivo conocidos de gráficas BI (fallback si la ruta completa no se detecta)
_KNOWN_PLOT_FILES = (
    "ventas_vs_reviews_scatter.png",
    "ventas_por_mes_lineas.png",
    "ventas_por_mes.png",
    "ventas_por_categoria_torta.png",
    "ventas_por_categoria.png",
    "top_vendedores.png",
    "top_clientes_ventas.png",
    "reviews_puntuacion.png",
    "dias_entrega_histograma.png",
)


def _find_plot_by_pattern(text: str, bases: tuple, seen: set) -> list[str]:
    """Si el texto menciona gráfica/gráfico generado, buscar plot_*.png o archivos conocidos en output/."""
    t = (text or "").lower()
    chart_hint = (
        "guardad" in t or "saved" in t or "gráfica" in t or "grafica" in t or
        "gráfico" in t or "grafico" in t or "generado" in t or "generada" in t or
        "torta" in t or "pie" in t or "barras" in t or "scatter" in t
    )
    if not text or not chart_hint:
        return []
    pattern = "plot_*.png"
    strict_type = False
    if "heatmap" in t or "mapa de calor" in t:
        pattern = "plot_heatmap_*.png"
        strict_type = True
    elif "scatter" in t or "dispersión" in t:
        pattern = "plot_scatter_*.png"
    elif "pie" in t or "torta" in t or "circular" in t:
        pattern = "plot_pie_*.png"
    elif "bar" in t or "barras" in t:
        pattern = "plot_bar_*.png"
    for base in bases:
        out_dir = (base / "output").resolve()
        if not out_dir.is_dir():
            continue
        for p in sorted(out_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True):
            s = str(p.resolve())
            if s not in seen:
                seen.add(s)
                return [s]
        if not strict_type and pattern != "plot_*.png":
            for p in sorted(out_dir.glob("plot_*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
                s = str(p.resolve())
                if s not in seen:
                    seen.add(s)
                    return [s]
        break
    return []


def extract_image_paths(text: str) -> list[str]:
    """
    Extrae rutas de imagen (.png, .jpg, .jpeg, .webp) del texto.
    Devuelve rutas absolutas que existen en disco (sin duplicados).
    """
    if not text or not text.strip():
        return []
    pattern = r"([^\s`\"'<>]+\.(?:png|jpg|jpeg|webp))"
    matches = re.findall(pattern, text, re.IGNORECASE)
    seen: set[str] = set()
    found: list[str] = []
    # Proyecto primero (gráficas se guardan ahí); cwd por si el path en el texto es relativo
    _proj = Path(__file__).resolve().parent.parent.parent
    bases = (_proj, Path.cwd())
    for m in matches:
        m_clean = m.strip()
        p = Path(m_clean)
        if p.is_absolute():
            resolved = p.resolve()
            if resolved.is_file() and str(resolved) not in seen:
                seen.add(str(resolved))
                found.append(str(resolved))
            else:
                # Ruta absoluta no existe (p.ej. cwd distinto): buscar por nombre en output/
                fname = p.name
                for base in bases:
                    candidate = (base / "output" / fname).resolve()
                    if candidate.is_file() and str(candidate) not in seen:
                        seen.add(str(candidate))
                        found.append(str(candidate))
                        break
        else:
            for base in bases:
                for subpath in [m_clean, f"output/{Path(m_clean).name}"]:
                    candidate = (base / subpath).resolve()
                    if candidate.is_file() and str(candidate) not in seen:
                        seen.add(str(candidate))
                        found.append(str(candidate))
                        break
                else:
                    continue
                break
    # Fallback: si no encontramos nada pero el texto menciona una gráfica guardada, buscar en output/
    if not found and any(fn in text for fn in _KNOWN_PLOT_FILES):
        for base in bases:
            out_dir = (base / "output").resolve()
            if out_dir.is_dir():
                for fn in _KNOWN_PLOT_FILES:
                    if fn in text:
                        candidate = out_dir / fn
                        if candidate.is_file() and str(candidate) not in seen:
                            seen.add(str(candidate))
                            found.append(str(candidate))
                            break
                if found:
                    break
    # Fallback para plot_query (plot_scatter_xxx.png, plot_bar_xxx.png, etc.)
    if not found:
        found = _find_plot_by_pattern(text, bases, seen)
    return found


def extract_excel_paths(text: str) -> list[str]:
    """
    Extrae rutas de archivos Excel (.xlsx) del texto.
    Devuelve rutas absolutas que existen en disco (sin duplicados).
    """
    if not text or not text.strip():
        return []
    pattern = r"([^\s`\"'<>]+\.xlsx)"
    matches = re.findall(pattern, text, re.IGNORECASE)
    seen: set[str] = set()
    found: list[str] = []
    _proj = Path(__file__).resolve().parent.parent.parent
    bases = (_proj, Path.cwd())
    for m in matches:
        m_clean = m.strip()
        p = Path(m_clean)
        if p.is_absolute():
            resolved = p.resolve()
            if resolved.is_file() and str(resolved) not in seen:
                seen.add(str(resolved))
                found.append(str(resolved))
            else:
                fname = p.name
                for base in bases:
                    candidate = (base / "output" / fname).resolve()
                    if candidate.is_file() and str(candidate) not in seen:
                        seen.add(str(candidate))
                        found.append(str(candidate))
                        break
        else:
            for base in bases:
                for subpath in [m_clean, f"output/{Path(m_clean).name}"]:
                    candidate = (base / subpath).resolve()
                    if candidate.is_file() and str(candidate) not in seen:
                        seen.add(str(candidate))
                        found.append(str(candidate))
                        break
                else:
                    continue
                break
    # Fallback: buscar export_*.xlsx en output/
    if not found and ("export" in text.lower() or "excel" in text.lower() or "guardado" in text.lower()):
        for base in bases:
            out_dir = (base / "output").resolve()
            if out_dir.is_dir():
                for p in sorted(out_dir.glob("export_*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True):
                    s = str(p.resolve())
                    if s not in seen:
                        seen.add(s)
                        found.append(s)
                        break
            if found:
                break
    return found


def _is_export_hashed_md(filename: str) -> bool:
    """True si es export_xxxxxxxx.md (tabla cruda antigua), no reporte con nombre descriptivo."""
    name = Path(filename).stem
    return bool(re.match(r"^export_[a-f0-9]{8}$", name, re.I))


def extract_markdown_paths(text: str) -> list[str]:
    """
    Extrae rutas de archivos Markdown (.md) del texto.
    EXCLUYE export_xxxxxxxx.md (tablas crudas). Solo incluye reportes con nombres descriptivos.
    """
    if not text or not text.strip():
        return []
    pattern = r"([^\s`\"'<>]+\.md)"
    matches = re.findall(pattern, text, re.IGNORECASE)
    seen: set[str] = set()
    found: list[str] = []
    _proj = Path(__file__).resolve().parent.parent.parent
    bases = (_proj, Path.cwd())
    for m in matches:
        m_clean = m.strip()
        if _is_export_hashed_md(m_clean):
            continue
        p = Path(m_clean)
        if p.is_absolute():
            resolved = p.resolve()
            if resolved.is_file() and str(resolved) not in seen:
                seen.add(str(resolved))
                found.append(str(resolved))
            else:
                fname = p.name
                for base in bases:
                    candidate = (base / "output" / fname).resolve()
                    if candidate.is_file() and str(candidate) not in seen:
                        seen.add(str(candidate))
                        found.append(str(candidate))
                        break
        else:
            for base in bases:
                for subpath in [m_clean, f"output/{Path(m_clean).name}"]:
                    candidate = (base / subpath).resolve()
                    if candidate.is_file() and str(candidate) not in seen:
                        seen.add(str(candidate))
                        found.append(str(candidate))
                        break
                else:
                    continue
                break
    if not found and ("reporte" in text.lower() or "informe" in text.lower() or "markdown" in text.lower() or "guardado" in text.lower()):
        for base in bases:
            out_dir = (base / "output").resolve()
            if out_dir.is_dir():
                for p in sorted(out_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
                    if _is_export_hashed_md(p.name):
                        continue
                    s = str(p.resolve())
                    if s not in seen:
                        seen.add(s)
                        found.append(s)
                        break
            if found:
                break
    return found


def friendly_query_error(error_message: str) -> str | None:
    """Si el error de DuckDB incluye 'Did you mean', devuelve un mensaje corto; si no, None."""
    if not error_message or "Did you mean" not in error_message:
        return None
    # DuckDB: '... Did you mean "telegram_messages"? ...'
    m = re.search(r'Did you mean\s+"([^"]+)"\s*\?', error_message)
    if m:
        return f"La tabla no existe. ¿Quisiste decir: {m.group(1)}?"
    return "La tabla no existe. Revisa el nombre."


def format_tool_reply(raw: str) -> str:
    """Convierte el resultado crudo de una herramienta en un mensaje legible para el usuario."""
    if not raw or not raw.strip():
        return "Sin resultados."
    s = raw.strip()
    # Si es un array JSON de objetos (ej. list_tables, resultados SQL)
    if s.startswith("["):
        try:
            data = json.loads(s)
            if not isinstance(data, list):
                return s
            if not data:
                return "No hay resultados."
            # list_tables: [{"table_name": "x"}, ...]
            if isinstance(data[0], dict) and "table_name" in data[0]:
                names = [str(row.get("table_name", "")) for row in data]
                return "Las tablas en la base de datos son: " + ", ".join(names) + "."
            # Lista genérica de filas
            if len(data) <= 5 and isinstance(data[0], dict):
                lines = []
                for i, row in enumerate(data):
                    parts = [f"{k}: {v}" for k, v in (row or {}).items()]
                    lines.append("  " + " | ".join(parts))
                return "Resultado:\n" + "\n".join(lines)
            return f"Se encontraron {len(data)} registro(s)." if len(data) > 3 else s
        except (json.JSONDecodeError, TypeError, IndexError, KeyError):
            pass
    # Si es un objeto JSON con "error", mensaje amigable para el usuario
    if s.startswith("{"):
        try:
            data = json.loads(s)
            if isinstance(data, dict) and "error" in data:
                err = str(data.get("error", ""))
                friendly = friendly_query_error(err)
                if friendly:
                    return friendly
                if "Catalog Error" in err or "Table" in err or "does not exist" in err:
                    return "Esa tabla no existe en la base de datos. Pregunta por las tablas disponibles o revisa el nombre."
                if "Query vacío" in err or "vacío" in err:
                    return "No se envió ninguna consulta."
                return "No se pudo completar la operación. Revisa la consulta o los datos."
            return s  # dejamos JSON si es objeto (inventario, etc.)
        except (json.JSONDecodeError, TypeError):
            pass
    return s
