#!/usr/bin/env bash
# Instala DuckClaw-Gateway y DuckClaw-Homeostasis-TaskAsk en systemd.
# Ejecutar desde el directorio del proyecto en el VPS: bash scripts/install_systemd_gateway.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SYSTEMD_DIR="${PROJECT_ROOT}/scripts/systemd"

cd "${PROJECT_ROOT}"

if [ ! -f "${SYSTEMD_DIR}/DuckClaw-Gateway.service" ]; then
  echo "Error: DuckClaw-Gateway.service no encontrado en ${SYSTEMD_DIR}"
  exit 1
fi

echo "Instalando unit files en /etc/systemd/system/..."
sudo cp "${SYSTEMD_DIR}/DuckClaw-Gateway.service" /etc/systemd/system/
sudo cp "${SYSTEMD_DIR}/DuckClaw-Homeostasis-TaskAsk.service" /etc/systemd/system/
sudo cp "${SYSTEMD_DIR}/DuckClaw-Homeostasis-TaskAsk.timer" /etc/systemd/system/
sudo systemctl daemon-reload

echo "Habilitando servicios..."
sudo systemctl enable DuckClaw-Gateway DuckClaw-Homeostasis-TaskAsk.timer

echo "Iniciando DuckClaw-Gateway..."
sudo systemctl start DuckClaw-Gateway

echo "Iniciando timer DuckClaw-Homeostasis-TaskAsk..."
sudo systemctl start DuckClaw-Homeostasis-TaskAsk.timer

echo "Listo. Ver estado: systemctl status DuckClaw-Gateway"
echo "Ver timer: systemctl list-timers DuckClaw-Homeostasis-TaskAsk.timer"
