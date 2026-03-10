#!/usr/bin/env bash
# Valida conectividad n8n (VPS) -> DuckClaw (Mac Mini) vía Tailscale
# Spec: DuckClaw Production Readiness (Corto Plazo)
#
# Ejecutar desde el VPS: bash scripts/validate_n8n_tailscale.sh
# Requiere: DUCKCLAW_TAILSCALE_IP (IP Tailscale de la Mac Mini) o pasarlo como $1

set -euo pipefail

MAC_IP="${1:-${DUCKCLAW_TAILSCALE_IP:-}}"
if [ -z "$MAC_IP" ]; then
    echo "Uso: $0 <IP_TAILSCALE_MAC_MINI>"
    echo "  O: DUCKCLAW_TAILSCALE_IP=100.x.y.z $0"
    exit 1
fi

API_URL="http://${MAC_IP}:8123"
HEALTH_URL="${API_URL}/health"

echo "=== Validación n8n -> DuckClaw (Tailscale) ==="
echo "Mac Mini (Tailscale): $MAC_IP"
echo "API: $API_URL"
echo ""

# 1. Health check sin auth
echo "[1] Health check (GET /health)..."
if curl -sf --connect-timeout 5 "$HEALTH_URL" >/dev/null; then
    echo "  OK: DuckClaw responde"
else
    echo "  FALLO: No se pudo conectar a $HEALTH_URL"
    echo "  Verifica: tailscale status, firewall (ufw allow in on tailscale0)"
    exit 1
fi

# 2. Con X-Tailscale-Auth-Key (si está configurado)
AUTH_KEY="${TAILSCALE_AUTH_KEY:-}"
if [ -n "$AUTH_KEY" ]; then
    echo "[2] Con X-Tailscale-Auth-Key..."
    if curl -sf --connect-timeout 5 -H "X-Tailscale-Auth-Key: $AUTH_KEY" "$HEALTH_URL" >/dev/null; then
        echo "  OK: Auth aceptada"
    else
        echo "  ADVERTENCIA: Auth key rechazada (puede ser normal si /health no requiere auth)"
    fi
else
    echo "[2] TAILSCALE_AUTH_KEY no configurado (omitido)"
fi

echo ""
echo "=== Validación completada ==="
echo "n8n puede llamar a DuckClaw en: $API_URL"
