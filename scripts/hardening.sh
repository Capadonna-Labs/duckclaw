#!/usr/bin/env bash
# DuckClaw VPS Hardening — UFW, SSH, LUKS (documentado)
# Spec: specs/DuckClaw Production Readiness (Corto Plazo).md
#
# Ejecutar en el VPS:
#   ssh user@vps 'bash -s' < scripts/hardening.sh
# O copiar y ejecutar localmente en el VPS (requiere sudo).
#
# Requisitos: Ubuntu/Debian con sudo.

set -euo pipefail

echo "=== DuckClaw VPS Hardening ==="
echo ""

# --- UFW: Firewall ---
if command -v ufw >/dev/null 2>&1; then
    echo "[UFW] Configurando firewall..."
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    sudo ufw allow 22/tcp comment "SSH"
    sudo ufw allow in on tailscale0 2>/dev/null || true
    sudo ufw allow 5678/tcp comment "n8n"
    sudo ufw allow 8123/tcp comment "DuckClaw API"
    sudo ufw --force enable 2>/dev/null || true
    echo "[UFW] Reglas aplicadas. Estado:"
    sudo ufw status verbose 2>/dev/null | head -30
else
    echo "[UFW] ufw no instalado. Instala con: sudo apt install ufw"
fi

echo ""

# --- SSH: Reforzar configuración ---
SSHD_CONFIG="/etc/ssh/sshd_config"
if [ -f "$SSHD_CONFIG" ]; then
    echo "[SSH] Verificando sshd_config..."
    if grep -q "^PermitRootLogin" "$SSHD_CONFIG" 2>/dev/null; then
        echo "[SSH] PermitRootLogin ya configurado."
    else
        echo "[SSH] Considera añadir: PermitRootLogin no"
        echo "      Y: PasswordAuthentication no (si usas solo claves)"
        echo "      Luego: sudo systemctl restart sshd"
    fi
else
    echo "[SSH] $SSHD_CONFIG no encontrado."
fi

echo ""

# --- LUKS: Cifrado de partición ---
echo "[LUKS] Cifrado de disco:"
echo "  LUKS requiere una partición dedicada y datos de cifrado."
echo "  No se puede automatizar sin conocer la partición destino."
echo "  Pasos manuales (Ubuntu):"
echo "    1. Crear partición: sudo fdisk /dev/sdX"
echo "    2. Cifrar: sudo cryptsetup luksFormat /dev/sdX1"
echo "    3. Abrir: sudo cryptsetup open /dev/sdX1 cryptdata"
echo "    4. Formatear: sudo mkfs.ext4 /dev/mapper/cryptdata"
echo "    5. Montar y migrar datos."
echo "  Documentación: https://help.ubuntu.com/community/EncryptedFilesystems"
echo ""

echo "=== Hardening completado ==="
