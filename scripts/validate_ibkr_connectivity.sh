#!/usr/bin/env bash
# Valida conectividad Mac Mini <-> VPS Capadonna <-> IB Gateway
# Ejecutar desde la Mac Mini (donde corre DuckClaw-Gateway)
# Uso: ./scripts/validate_ibkr_connectivity.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# Cargar .env si existe (valores por defecto en el script)
[[ -f .env ]] && while IFS='=' read -r k v; do
  [[ "$k" == IBKR_PORTFOLIO_API_URL ]] && IBKR_URL="$v"
  [[ "$k" == IBKR_PORTFOLIO_API_KEY ]] && IBKR_KEY="$v"
  [[ "$k" == DUCKCLAW_TAILSCALE_AUTH_KEY ]] && TAILSCALE_KEY="$v"
done < <(grep -E "^IBKR_PORTFOLIO_API_URL=|^IBKR_PORTFOLIO_API_KEY=|^DUCKCLAW_TAILSCALE_AUTH_KEY=" .env 2>/dev/null || true)

IBKR_URL="${IBKR_URL:-http://100.97.151.69:8002/api/portfolio/summary}"
IBKR_KEY="${IBKR_PORTFOLIO_API_KEY:-shared_secret_tailscale}"
TAILSCALE_KEY="${DUCKCLAW_TAILSCALE_AUTH_KEY:-n8n_secret_key_12345}"

echo "=============================================="
echo "Validación IBKR: Mac Mini <-> VPS <-> IB Gateway"
echo "=============================================="
echo ""

echo "1. Capadonna API (VPS :8002) - /api/portfolio/summary"
echo "   URL: $IBKR_URL"
SUMMARY=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $IBKR_KEY" -H "Accept: application/json" "$IBKR_URL")
HTTP=$(echo "$SUMMARY" | tail -1)
BODY=$(echo "$SUMMARY" | sed '$d')
echo "   HTTP: $HTTP"
echo "   Body: $BODY"
echo ""

echo "2. Capadonna API - /api/positions (fallback)"
POS_URL="http://100.97.151.69:8002/api/positions"
POS=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $IBKR_KEY" "$POS_URL")
echo "   HTTP: $(echo "$POS" | tail -1)"
echo "   Body: $(echo "$POS" | sed '$d')"
echo ""

echo "3. DuckClaw Gateway (Mac Mini :8000) - chat portfolio"
CHAT=$(curl -s -X POST "http://localhost:8000/api/v1/agent/chat" \
  -H "X-Tailscale-Auth-Key: $TAILSCALE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"Dame un resumen de mi portfolio","session_id":"validate-ibkr","stream":false}')
echo "   Response: $(echo "$CHAT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('response','')[:200]+'...' if len(d.get('response',''))>200 else d.get('response',''))" 2>/dev/null || echo "$CHAT")"
echo ""

echo "=============================================="
echo "Diagnóstico:"
if echo "$BODY" | grep -q '"portfolio":\[\]' && echo "$BODY" | grep -q '"total_value":0'; then
  echo "  ⚠ Portfolio VACÍO. Revisar en el VPS:"
  echo "     - capadonna-observability.service tiene IB_ENV=live (no paper)"
  echo "     - IB Gateway/TWS conectado a cuenta LIVE (puerto 7496)"
  echo "     - sudo systemctl status capadonna-observability"
  echo "     - sudo journalctl -u capadonna-observability -n 30"
else
  echo "  ✓ Portfolio con datos."
fi
echo "=============================================="
