#!/usr/bin/env bash
# Tailscale Mesh Setup — VPS (Ubuntu/Debian)
# Spec: specs/Arquitectura_de_Red_Distribuida_(Tailscale_Mesh).md
# Ejecutar en el VPS: bash tailscale_install_vps.sh
# O vía SSH: ssh user@vps 'bash -s' < scripts/tailscale_install_vps.sh

set -euo pipefail

echo "=== Tailscale Mesh Setup (VPS) ==="
echo ""

# Instalar Tailscale
if ! command -v tailscale >/dev/null 2>&1; then
    echo "Instalando Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
else
    echo "Tailscale ya está instalado."
fi

echo ""
echo "Ejecutando tailscale up (autenticación interactiva)..."
echo "Si no tienes cuenta, créala en https://login.tailscale.com"
tailscale up

echo ""
echo "Configurando firewall..."
if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow in on tailscale0
    sudo ufw allow 5678  # n8n
    sudo ufw --force enable 2>/dev/null || true
    echo "Firewall: tráfico permitido en tailscale0 y puerto 5678 (n8n)"
else
    echo "ufw no instalado. Configura manualmente el firewall."
fi

echo ""
echo "=== IP Tailscale asignada ==="
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "No disponible")
echo "IP del VPS en la Tailnet: $TAILSCALE_IP"
echo ""
echo "Verificación hacia Mac Mini:"
echo "  curl http://<MAC_TAILSCALE_IP>:8123/health"
echo ""
echo "n8n: http://${TAILSCALE_IP}:5678 (o desde la IP pública si está expuesto)"
echo ""
