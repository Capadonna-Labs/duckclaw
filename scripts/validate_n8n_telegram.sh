#!/bin/bash
#
# Valida la integración n8n + Telegram + API Gateway (Mac Mini) vía Tailscale.
# Uso: ./scripts/validate_n8n_telegram.sh [VPS_HOST]
#   VPS_HOST: hostname o IP del VPS (ej. user@100.x.y.z o user@vps.example.com)
#
set -e

VPS_HOST="${1:-}"
MAC_MINI_IP="${MAC_MINI_TAILSCALE_IP:-100.97.151.69}"
GATEWAY_URL="http://${MAC_MINI_IP}:8000"

echo "=== Validación n8n + Telegram + API Gateway ==="
echo ""

# 1. Tailscale en Mac Mini (local)
echo "1. Tailscale (Mac Mini):"
if command -v tailscale &>/dev/null; then
  TS_STATUS=$(tailscale status 2>/dev/null || echo "Down")
  if echo "$TS_STATUS" | grep -q "Active"; then
    echo "   ✓ Tailscale activo"
    tailscale ip -4 2>/dev/null | head -1 | xargs -I {} echo "   IP: {}"
  else
    echo "   ✗ Tailscale no activo. Ejecuta: tailscale up"
  fi
else
  echo "   ⚠ tailscale no instalado"
fi
echo ""

# 2. API Gateway local (Mac Mini)
echo "2. API Gateway (Mac Mini :8000):"
if curl -sf --connect-timeout 3 "${GATEWAY_URL}/health" >/dev/null 2>&1; then
  echo "   ✓ Gateway respondiendo en ${GATEWAY_URL}"
  curl -s "${GATEWAY_URL}/health" | head -1
else
  echo "   ✗ No se puede conectar a ${GATEWAY_URL}"
  echo "   Asegúrate de que DuckClaw-Gateway esté corriendo: pm2 start ecosystem.hybrid.config.cjs"
fi
echo ""

# 3. Reiniciar n8n en VPS (si se proporciona host)
if [[ -n "$VPS_HOST" ]]; then
  echo "3. Reiniciando n8n en VPS (${VPS_HOST})..."
  if ssh -o ConnectTimeout=5 -o BatchMode=yes "$VPS_HOST" "sudo systemctl restart n8n 2>/dev/null || (docker restart n8n 2>/dev/null) || echo 'n8n no encontrado como systemd ni docker'" 2>/dev/null; then
    echo "   ✓ Comando ejecutado"
    sleep 3
    echo "   Verificando n8n..."
    ssh -o ConnectTimeout=5 "$VPS_HOST" "curl -sf http://localhost:5678/healthz 2>/dev/null && echo 'n8n OK' || systemctl is-active n8n 2>/dev/null || echo 'Revisa manualmente'"
  else
    echo "   ✗ No se pudo conectar por SSH. Verifica: ssh $VPS_HOST"
  fi
else
  echo "3. Reinicio n8n: omitido (no se pasó VPS_HOST)"
  echo "   Para reiniciar: ./scripts/validate_n8n_telegram.sh user@100.x.y.z"
fi
echo ""

# 4. Test de integración (desde Mac hacia Gateway)
echo "4. Test API /agent/chat (requiere DUCKCLAW_TAILSCALE_AUTH_KEY):"
AUTH_KEY="${DUCKCLAW_TAILSCALE_AUTH_KEY:-}"
if [[ -n "$AUTH_KEY" ]]; then
  RESP=$(curl -sf -X POST "${GATEWAY_URL}/api/v1/agent/chat" \
    -H "X-Tailscale-Auth-Key: ${AUTH_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"message":"hola","session_id":"test-validate","stream":false}' 2>/dev/null || echo '{"error":"fail"}')
  if echo "$RESP" | grep -q '"response"'; then
    echo "   ✓ API responde correctamente"
  else
    echo "   ✗ Error en la API. Respuesta: $RESP"
  fi
else
  echo "   ⚠ DUCKCLAW_TAILSCALE_AUTH_KEY no definida. Exporta en .env o ejecuta: export DUCKCLAW_TAILSCALE_AUTH_KEY=tu_clave"
fi
echo ""
echo "=== Resumen ==="
echo "• n8n debe usar /api/v1/agent/chat (no /agent/finanz/chat) para soportar /role"
echo "• n8n debe usar X-Tailscale-Auth-Key en las peticiones al API"
echo "• El webhook de Telegram debe apuntar a n8n (no al bot Python)"
