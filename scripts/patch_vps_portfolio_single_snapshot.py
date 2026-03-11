#!/usr/bin/env python3
"""Patch observability_api: use single get_account_snapshot() in get_portfolio_summary so cash is populated.
Run on VPS: python3 /tmp/patch_vps_portfolio_single_snapshot.py
"""
from pathlib import Path
path = Path("/home/capadonna/projects/Capadonna-Driller/services/observability_api.py")
text = path.read_text(encoding="utf-8")

# Replace get_portfolio_summary to fetch snapshot once and derive positions + metrics from it
old_block = r'''@app.get("/api/portfolio/summary")
async def get_portfolio_summary():
    """Obtener resumen de portfolio"""
    try:
        positions = get_trading_positions()
        metrics = get_account_metrics()
        
        # Agrupar por símbolo
        portfolio = {}
        for pos in positions:
            symbol = pos.get('symbol', 'UNKNOWN')
            if symbol not in portfolio:
                portfolio[symbol] = {
                    "symbol": symbol,
                    "quantity": 0,
                    "market_value": 0,
                    "unrealized_pnl": 0
                }
            
            portfolio[symbol]["quantity"] += pos.get('position', 0)
            portfolio[symbol]["market_value"] += pos.get('marketValue', 0)
            portfolio[symbol]["unrealized_pnl"] += pos.get('unrealizedPNL', 0)
        
        return JSONResponse(content={
            "portfolio": list(portfolio.values()),
            "total_value": metrics.get('net_liquidation', 0) or metrics.get('total_market_value', 0),
            "cash": metrics.get('total_cash', 0),
            "cash_balance": metrics.get('total_cash', 0),
            "count": len(portfolio),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error en get_portfolio_summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))'''

new_block = '''@app.get("/api/portfolio/summary")
async def get_portfolio_summary():
    """Obtener resumen de portfolio (una sola llamada a get_account_snapshot para evitar timeout y tener cash)."""
    try:
        snapshot = get_account_snapshot()
        if not snapshot:
            return JSONResponse(content={
                "portfolio": [], "total_value": 0, "cash": 0, "cash_balance": 0,
                "count": 0, "timestamp": datetime.now().isoformat(), "error": "snapshot_unavailable"
            })
        positions = snapshot.get("positions") or []
        # Extraer métricas de cuenta desde el mismo snapshot (evita segunda conexión)
        account_data = None
        for key, value in snapshot.items():
            if key.startswith("account_") and isinstance(value, dict) and key not in ("account_summary", "account_values"):
                account_data = value
                break
        if account_data:
            try:
                total_cash = float(account_data.get("TotalCashValue", 0) or 0)
                net_liquidation = float(account_data.get("NetLiquidation", 0) or 0)
            except (TypeError, ValueError):
                total_cash = net_liquidation = 0
        else:
            total_cash = net_liquidation = 0
        stats = snapshot.get("stats") or {}
        total_market_value = stats.get("total_market_value", 0) or 0
        # Agrupar por símbolo (positions usan marketValue por compatibilidad)
        portfolio = {}
        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            if symbol not in portfolio:
                portfolio[symbol] = {"symbol": symbol, "quantity": 0, "market_value": 0, "unrealized_pnl": 0}
            portfolio[symbol]["quantity"] += pos.get("position", 0)
            portfolio[symbol]["market_value"] += pos.get("marketValue", 0)
            portfolio[symbol]["unrealized_pnl"] += pos.get("unrealizedPNL", 0)
        total_value = net_liquidation if net_liquidation else total_market_value
        return JSONResponse(content={
            "portfolio": list(portfolio.values()),
            "total_value": total_value,
            "cash": total_cash,
            "cash_balance": total_cash,
            "count": len(portfolio),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error en get_portfolio_summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))'''

if old_block not in text:
    print("OLD block not found (maybe already patched)")
    exit(2)
text = text.replace(old_block, new_block)
path.write_text(text, encoding="utf-8")
print("Patched: single snapshot in get_portfolio_summary")
