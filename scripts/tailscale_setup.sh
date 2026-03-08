#!/usr/bin/env bash
# Tailscale Mesh Setup — Mac Mini / Linux local
# Spec: specs/Arquitectura_de_Red_Distribuida_(Tailscale_Mesh).md
# Instala Tailscale, autentica y configura firewall para la Tailnet.

set -euo pipefail

API_PORT="${DUCKCLAW_API_PORT:-8123}"

echo "=== Tailscale Mesh Setup ==="
echo ""

# Detectar SO
if [[ "$(uname)" == "Darwin" ]]; then
    OS="macos"
elif [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS="${ID:-linux}"
else
    OS="linux"
fi

echo "Sistema detectado: $OS"
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

if [[ "$OS" == "macos" ]]; then
    echo "macOS: Asegúrate de permitir Tailscale en Preferencias del Sistema > Seguridad y Privacidad > Firewall"
    echo "No se requiere ufw en macOS."
else
    if command -v ufw >/dev/null 2>&1; then
        sudo ufw allow in on tailscale0
        sudo ufw --force enable 2>/dev/null || true
        echo "Firewall: tráfico permitido en interfaz tailscale0"
    else
        echo "ufw no instalado. Configura manualmente el firewall para permitir tailscale0."
    fi
fi

echo ""
echo "=== IP Tailscale asignada ==="
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "No disponible")
echo "Tu IP en la Tailnet: $TAILSCALE_IP"
echo ""
echo "Verificación: desde otro nodo de la Tailnet, ejecuta:"
echo "  curl http://${TAILSCALE_IP}:${API_PORT}/health"
echo ""
echo "Para usar puerto 8000 (según spec): DUCKCLAW_API_PORT=8000 python -m duckclaw.agents.graph_server --port 8000"
echo ""
