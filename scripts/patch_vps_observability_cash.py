#!/usr/bin/env python3
"""Aplica patch en observability_api.py del VPS para incluir cash en /api/portfolio/summary.
Ejecutar en el VPS: python3 patch_vps_observability_cash.py
O desde DuckClaw: ssh capadonna@VPS 'cd /home/capadonna/projects/Capadonna-Driller && python3 -s' < scripts/patch_vps_observability_cash.py
"""
import sys
from pathlib import Path

path = Path("/home/capadonna/projects/Capadonna-Driller/services/observability_api.py")
if len(sys.argv) > 1:
    path = Path(sys.argv[1])

if not path.exists():
    print("File not found:", path)
    sys.exit(1)

text = path.read_text(encoding="utf-8")

old = '''        return JSONResponse(content={
            "portfolio": list(portfolio.values()),
            "total_value": metrics.get('total_market_value', 0),
            "count": len(portfolio),
            "timestamp": datetime.now().isoformat()
        })'''

new = '''        return JSONResponse(content={
            "portfolio": list(portfolio.values()),
            "total_value": metrics.get('net_liquidation', 0) or metrics.get('total_market_value', 0),
            "cash": metrics.get('total_cash', 0),
            "cash_balance": metrics.get('total_cash', 0),
            "count": len(portfolio),
            "timestamp": datetime.now().isoformat()
        })'''

if old not in text:
    print("Pattern not found (maybe already patched or different format)")
    sys.exit(2)

text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("Patched:", path)
