"""
Exportación a Markdown: informes con insights (no tablas crudas).
Para tablas crudas usar export_to_excel.

- create_report_markdown: MD con referencias a imágenes (rutas relativas).
- create_report_html: HTML con imágenes embebidas en base64 (un solo archivo para Telegram).
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Optional


def _slug(s: str) -> str:
    """Convierte texto a slug para nombre de archivo: ventas_noviembre_2017."""
    if not s or not s.strip():
        return "reporte"
    t = s.strip().lower()
    t = t.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    t = re.sub(r"[^a-z0-9\s\-_]", "", t)
    t = re.sub(r"[\s\-]+", "_", t).strip("_")
    return t[:60] or "reporte"


def create_report_markdown(
    save_dir: str = "output",
    filename: str = "reporte",
    title: str = "Informe",
    insights: str = "",
    summary_data: Optional[list[dict[str, Any]]] = None,
    image_refs: Optional[list[str]] = None,
) -> str:
    """
    Crea un informe en Markdown con insights, análisis y opcionalmente gráficas.
    NO usar para exportar tablas crudas (usar export_to_excel).

    - filename: nombre descriptivo sin extensión (ej. ventas_noviembre_2017, kpis_nov_2017).
    - title: título del informe.
    - insights: contenido markdown con análisis, conclusiones, hallazgos.
    - summary_data: opcional, lista de dicts para tabla resumen (máx 10 filas).
    - image_refs: opcional, nombres de imágenes en output/ (ej. ventas_por_mes.png).

    Devuelve la ruta del archivo generado.
    """
    out_dir = Path(save_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    slug = _slug(filename) if filename else "reporte"
    out_path = out_dir / f"{slug}.md"

    lines: list[str] = []
    lines.append(f"# {title or 'Informe'}\n")

    if insights and insights.strip():
        lines.append("## Insights\n")
        lines.append(insights.strip())
        lines.append("")

    if summary_data and len(summary_data) > 0:
        rows = summary_data[:10]
        cols = list(rows[0].keys()) if rows else []
        lines.append("## Resumen de datos\n")
        header = "| " + " | ".join(str(c) for c in cols) + " |"
        sep = "|" + "|".join("---" for _ in cols) + "|"
        lines.append(header)
        lines.append(sep)
        for row in rows:
            cells = [_md_escape(str(row.get(c, ""))) for c in cols]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    if image_refs:
        lines.append("## Gráficas\n")
        for ref in image_refs[:5]:
            fname = Path(ref).name if "/" in ref or "\\" in ref else ref
            lines.append(f"![{fname}]({fname})\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return f"Archivo Markdown guardado: {out_path}"


def _md_escape(s: str) -> str:
    """Escapa caracteres que rompen tablas Markdown."""
    return str(s).replace("|", "\\|").replace("\n", " ").replace("\r", "")[:200]


def _md_to_html(md: str) -> str:
    """Conversión básica MD → HTML para reportes."""
    if not md or not md.strip():
        return ""
    html_parts: list[str] = []
    in_table = False
    for line in md.split("\n"):
        s = line.rstrip()
        if s.startswith("# "):
            html_parts.append(f"<h1>{_html_escape(s[2:])}</h1>")
        elif s.startswith("## "):
            html_parts.append(f"<h2>{_html_escape(s[3:])}</h2>")
        elif s.startswith("### "):
            html_parts.append(f"<h3>{_html_escape(s[4:])}</h3>")
        elif s.startswith("|") and "|" in s[1:]:
            if not in_table:
                in_table = True
                html_parts.append("<table border='1' cellpadding='6'>")
            cells = [c.strip() for c in s.split("|")[1:-1]]
            tag = "th" if "---" in s or all(c.replace("-", "").strip() == "" for c in cells) else "td"
            if tag == "th" and "---" in s:
                continue
            html_parts.append("<tr>" + "".join(f"<{tag}>{_html_escape(c)}</{tag}>" for c in cells) + "</tr>")
        else:
            if in_table:
                html_parts.append("</table>")
                in_table = False
            if s.strip():
                t = _html_escape(s)
                t = re.sub(r"\*\*(.+?)\*\*", lambda m: f"<b>{m.group(1)}</b>", t)
                t = re.sub(r"\*(.+?)\*", lambda m: f"<em>{m.group(1)}</em>", t)
                html_parts.append(f"<p>{t}</p>")
            else:
                html_parts.append("<br/>")
    if in_table:
        html_parts.append("</table>")
    return "\n".join(html_parts)


def _html_escape(s: str) -> str:
    """Escapa HTML."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def create_report_html(
    md_path: str | Path,
    image_paths: list[str | Path],
    *,
    save_dir: str | Path | None = None,
    filename: str | None = None,
) -> str:
    """
    Crea un HTML con el contenido del MD y las imágenes embebidas en base64.
    Un solo archivo para enviar por Telegram (insights + gráficas dentro).

    - md_path: ruta al .md generado por create_report_markdown.
    - image_paths: rutas absolutas a las imágenes a embebir.
    - save_dir: directorio de salida (por defecto el mismo que el MD).
    - filename: nombre sin extensión (por defecto el del MD + _html).

    Devuelve la ruta del archivo HTML generado.
    """
    md_file = Path(md_path).resolve()
    if not md_file.is_file():
        return ""
    md_content = md_file.read_text(encoding="utf-8")
    # Quitar sección Gráficas del MD (la reemplazamos con imágenes embebidas)
    md_content = re.sub(r"\n## Gráficas\n[\s\S]*?(?=\n## |\Z)", "\n", md_content, flags=re.IGNORECASE)
    html_body = _md_to_html(md_content)

    # Embebir imágenes en base64
    img_sections: list[str] = []
    for p in image_paths[:10]:
        img_path = Path(p).resolve()
        if not img_path.is_file():
            continue
        try:
            b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
            ext = img_path.suffix.lower()
            mime = "image/png" if ext == ".png" else "image/jpeg" if ext in (".jpg", ".jpeg") else "image/webp"
            img_sections.append(f'<figure><img src="data:{mime};base64,{b64}" alt="{img_path.name}" style="max-width:100%;"/><figcaption>{_html_escape(img_path.stem)}</figcaption></figure>')
        except Exception:
            continue

    if img_sections:
        html_body += "\n<h2>Gráficas</h2>\n" + "\n".join(img_sections)

    out_dir = Path(save_dir) if save_dir else md_file.parent
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = filename or md_file.stem
    if not filename and not slug.endswith("_html"):
        slug = f"{slug}_html"
    out_path = out_dir / f"{slug}.html"

    html_full = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"/><title>{_html_escape(md_file.stem)}</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:20px auto;padding:0 20px;}} table{{border-collapse:collapse;width:100%;}} img{{max-width:100%;}}</style>
</head>
<body>
{html_body}
</body>
</html>"""
    out_path.write_text(html_full, encoding="utf-8")
    return str(out_path)
