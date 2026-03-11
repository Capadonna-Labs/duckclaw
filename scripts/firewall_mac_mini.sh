#!/bin/bash
#
# Firewall para Hybrid Mesh: permitir tráfico Tailscale al puerto 8000 (DuckClaw-Gateway).
#
# macOS usa pf (Packet Filter), no ufw. Linux usa ufw.
# Ejecutar: ./scripts/firewall_mac_mini.sh
#
set -e

PORT=8000

if [[ "$(uname)" == "Darwin" ]]; then
  echo "=== macOS (pf) ==="
  echo "macOS no incluye ufw. Opciones:"
  echo "  1. Preferencias del Sistema > Seguridad y privacidad > Firewall"
  echo "     Activar firewall y permitir DuckClaw-Gateway si aparece."
  echo "  2. Configurar pf manualmente para permitir tailscale0:"
  echo "     - Crear /etc/pf.anchors/duckclaw con reglas para tailscale0"
  echo "     - Cargar en /etc/pf.conf"
  echo ""
  echo "Por defecto, si el firewall de macOS está desactivado, Tailscale"
  echo "puede alcanzar el puerto ${PORT} sin restricciones."
else
  echo "=== Linux (ufw) ==="
  if command -v ufw &>/dev/null; then
    echo "Permitiendo tráfico en tailscale0 al puerto ${PORT}..."
    sudo ufw allow in on tailscale0 to any port ${PORT} proto tcp
    sudo ufw default deny incoming
    sudo ufw --force enable
    echo "Reglas aplicadas. Verificar: sudo ufw status"
  else
    echo "ufw no instalado. Instalar con: sudo apt install ufw"
    exit 1
  fi
fi
