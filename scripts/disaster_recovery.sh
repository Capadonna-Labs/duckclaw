#!/usr/bin/env bash
# DisasterRecoveryNode — snapshot cifrado de DuckDB y models/active/
# Spec: specs/Auditoria_Arquitectura_y_Mejoras_Prioridad_Alta.md
#
# Uso:
#   ./scripts/disaster_recovery.sh [--encrypt] [--upload]
# Requiere: restic (opcional), rclone o aws s3 (opcional)
#
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${DUCKCLAW_BACKUP_DIR:-$PROJECT_ROOT/backups}"
DATE=$(date +%Y%m%d)
SNAPSHOT_NAME="duckclaw-$DATE"

mkdir -p "$BACKUP_DIR"

echo "[DisasterRecovery] Snapshot $SNAPSHOT_NAME"

# 1. Copiar DuckDB
if [ -d "$PROJECT_ROOT/db" ]; then
  mkdir -p "$BACKUP_DIR/$SNAPSHOT_NAME/db"
  cp -a "$PROJECT_ROOT/db/"*.duckdb "$BACKUP_DIR/$SNAPSHOT_NAME/db/" 2>/dev/null || true
  echo "  - db/ copiado"
fi

# 2. Copiar models/active/
if [ -d "$PROJECT_ROOT/models/active" ]; then
  mkdir -p "$BACKUP_DIR/$SNAPSHOT_NAME/models"
  cp -a "$PROJECT_ROOT/models/active" "$BACKUP_DIR/$SNAPSHOT_NAME/models/" 2>/dev/null || true
  echo "  - models/active/ copiado"
fi

# 3. Cifrado con Restic (si está instalado y RESTIC_REPO configurado)
if command -v restic &>/dev/null && [ -n "${RESTIC_REPO:-}" ]; then
  restic backup "$BACKUP_DIR/$SNAPSHOT_NAME" --tag "$SNAPSHOT_NAME"
  echo "  - Cifrado con Restic"
fi

# 4. Subida a S3/R2 (si rclone o aws está configurado)
if [ "${1:-}" = "--upload" ] && command -v rclone &>/dev/null && [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$BACKUP_DIR/$SNAPSHOT_NAME" "$RCLONE_REMOTE:duckclaw-backups/$SNAPSHOT_NAME"
  echo "  - Subido a $RCLONE_REMOTE"
fi

echo "[DisasterRecovery] Completado: $BACKUP_DIR/$SNAPSHOT_NAME"
