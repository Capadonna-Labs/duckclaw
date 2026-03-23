from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import duckdb


_DDL_USER_VAULTS = """
CREATE TABLE IF NOT EXISTS main.user_vaults (
    user_id VARCHAR,
    vault_id VARCHAR,
    vault_name VARCHAR,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, vault_id)
);
"""


def _safe_user_id(user_id: Any) -> str:
    raw = (str(user_id or "").strip() or "default").lower()
    return re.sub(r"[^a-z0-9_-]", "_", raw)[:128] or "default"


def _slug_vault_id(name: Any) -> str:
    raw = str(name or "").strip().lower()
    if not raw:
        return ""
    slug = re.sub(r"[^a-z0-9_-]+", "_", raw)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:64]


def db_root() -> Path:
    """
    Directorio `db/` del monorepo.

    Si el proceso arranca con cwd distinto del repo (p. ej. `services/db-writer`),
    definir `DUCKCLAW_REPO_ROOT` apuntando a la raíz del monorepo; si no, se usa
    `Path(\"db\").resolve()` relativo al cwd (comportamiento legacy).
    """
    env_root = (os.environ.get("DUCKCLAW_REPO_ROOT") or "").strip()
    if env_root:
        return (Path(env_root).expanduser().resolve() / "db")
    return Path("db").resolve()


def system_db_path() -> Path:
    root = db_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "system.duckdb"


def user_vault_dir(user_id: Any) -> Path:
    path = db_root() / "private" / _safe_user_id(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def vault_file_path(user_id: Any, vault_id: str) -> Path:
    vid = _slug_vault_id(vault_id) or "default"
    return user_vault_dir(user_id) / f"{vid}.duckdb"


def ensure_registry() -> None:
    db = duckdb.connect(str(system_db_path()), read_only=False)
    try:
        db.execute(_DDL_USER_VAULTS)
    finally:
        db.close()


def _touch_duckdb_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        db = duckdb.connect(str(path), read_only=False)
        try:
            db.execute("SELECT 1")
        finally:
            db.close()
    except Exception:
        # Best-effort bootstrap: si hay lock concurrente, no bloquear el flujo.
        # El archivo/DB podrá existir ya y ser usable por el proceso principal.
        pass


def _discover_existing_user_vaults(uid: str) -> list[str]:
    """Return vault_ids discovered from existing *.duckdb files in user's folder."""
    folder = user_vault_dir(uid)
    discovered: list[str] = []
    for p in sorted(folder.glob("*.duckdb")):
        stem = (p.stem or "").strip().lower()
        vid = _slug_vault_id(stem)
        if vid:
            discovered.append(vid)
    return discovered


def _discover_existing_user_vaults_with_size(uid: str) -> list[tuple[str, int]]:
    folder = user_vault_dir(uid)
    out: list[tuple[str, int]] = []
    for p in folder.glob("*.duckdb"):
        vid = _slug_vault_id((p.stem or "").strip().lower())
        if not vid:
            continue
        try:
            size = int(p.stat().st_size)
        except Exception:
            size = 0
        out.append((vid, size))
    # Largest first so real vaults like finanzdb1 outrank fresh default files.
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def _sync_registry_with_files(sysdb: duckdb.DuckDBPyConnection, uid: str) -> None:
    """Ensure every discovered *.duckdb exists in registry as an inactive vault."""
    for vid, _sz in _discover_existing_user_vaults_with_size(uid):
        sysdb.execute(
            """
            INSERT INTO main.user_vaults (user_id, vault_id, vault_name, is_active)
            VALUES (?, ?, ?, FALSE)
            ON CONFLICT (user_id, vault_id) DO NOTHING
            """,
            [uid, vid, vid],
        )


def _bootstrap_default_if_missing(user_id: Any) -> tuple[str, Path]:
    uid = _safe_user_id(user_id)
    ensure_registry()
    sysdb = duckdb.connect(str(system_db_path()), read_only=False)
    try:
        rows = sysdb.execute(
            "SELECT vault_id FROM main.user_vaults WHERE user_id = ? AND is_active = TRUE LIMIT 1",
            [uid],
        ).fetchall()
        if rows:
            vault_id = str(rows[0][0] or "default").strip() or "default"
            path = vault_file_path(uid, vault_id)

            # If active is default but there is a stronger existing non-default vault,
            # auto-promote it (typical migration/restart scenario).
            if vault_id == "default":
                discovered_with_size = _discover_existing_user_vaults_with_size(uid)
                non_default = [(vid, sz) for vid, sz in discovered_with_size if vid != "default"]
                if non_default:
                    # Registry signal: if only default is known, or default is tiny/empty, switch.
                    count_non_default_rows = sysdb.execute(
                        "SELECT COUNT(*) FROM main.user_vaults WHERE user_id = ? AND vault_id <> 'default'",
                        [uid],
                    ).fetchone()
                    known_non_default = int((count_non_default_rows or [0])[0] or 0)
                    default_size = 0
                    try:
                        default_size = int(path.stat().st_size) if path.exists() else 0
                    except Exception:
                        default_size = 0
                    should_promote = known_non_default == 0 or default_size <= 12288
                    if should_promote:
                        chosen, _ = non_default[0]
                        chosen_path = vault_file_path(uid, chosen)
                        _touch_duckdb_file(chosen_path)
                        sysdb.execute("UPDATE main.user_vaults SET is_active = FALSE WHERE user_id = ?", [uid])
                        # Register discovered files if missing
                        _sync_registry_with_files(sysdb, uid)
                        sysdb.execute(
                            """
                            INSERT INTO main.user_vaults (user_id, vault_id, vault_name, is_active)
                            VALUES (?, ?, ?, TRUE)
                            ON CONFLICT (user_id, vault_id) DO UPDATE SET is_active=TRUE
                            """,
                            [uid, chosen, chosen],
                        )
                        return chosen, chosen_path

            _touch_duckdb_file(path)
            return vault_id, path

        # No active vault in registry:
        # if there are existing .duckdb files, adopt one (prefer non-default),
        # otherwise create/use default.
        discovered = _discover_existing_user_vaults(uid)
        chosen = ""
        non_default = [v for v in discovered if v != "default"]
        if non_default:
            chosen = non_default[0]
        elif discovered:
            chosen = discovered[0]
        else:
            chosen = "default"

        chosen_path = vault_file_path(uid, chosen)
        _touch_duckdb_file(chosen_path)
        default_path = vault_file_path(uid, "default")
        sysdb.execute("UPDATE main.user_vaults SET is_active = FALSE WHERE user_id = ?", [uid])
        # Register all discovered files as known vaults (inactive by default).
        _sync_registry_with_files(sysdb, uid)
        # Ensure chosen exists in registry and set active.
        sysdb.execute(
            """
            INSERT INTO main.user_vaults (user_id, vault_id, vault_name, is_active)
            VALUES (?, ?, ?, TRUE)
            ON CONFLICT (user_id, vault_id) DO UPDATE SET is_active=TRUE
            """,
            [uid, chosen, chosen],
        )
        return chosen, chosen_path
    finally:
        sysdb.close()


def resolve_active_vault(user_id: Any) -> tuple[str, str]:
    vault_id, path = _bootstrap_default_if_missing(user_id)
    return vault_id, str(path.resolve())


def list_vaults(user_id: Any) -> list[dict[str, Any]]:
    uid = _safe_user_id(user_id)
    ensure_registry()
    sysdb = duckdb.connect(str(system_db_path()), read_only=False)
    try:
        _sync_registry_with_files(sysdb, uid)
        rows = sysdb.execute(
            """
            SELECT vault_id, vault_name, is_active, created_at
            FROM main.user_vaults
            WHERE user_id = ?
            ORDER BY created_at, vault_id
            """,
            [uid],
        ).fetchall()
    finally:
        sysdb.close()

    out: list[dict[str, Any]] = []
    for vault_id, vault_name, is_active, created_at in rows:
        path = vault_file_path(uid, str(vault_id))
        size = path.stat().st_size if path.exists() else 0
        out.append(
            {
                "vault_id": str(vault_id),
                "vault_name": str(vault_name or vault_id or ""),
                "is_active": bool(is_active),
                "created_at": str(created_at or ""),
                "db_path": str(path.resolve()),
                "size_bytes": int(size),
            }
        )
    if not out:
        resolve_active_vault(uid)
        return list_vaults(uid)
    return out


def create_vault(user_id: Any, vault_name: str) -> dict[str, Any]:
    uid = _safe_user_id(user_id)
    name = (vault_name or "").strip() or "vault"
    base = _slug_vault_id(name) or "vault"
    ensure_registry()
    sysdb = duckdb.connect(str(system_db_path()), read_only=False)
    try:
        suffix = 1
        vault_id = base
        while True:
            row = sysdb.execute(
                "SELECT 1 FROM main.user_vaults WHERE user_id = ? AND vault_id = ? LIMIT 1",
                [uid, vault_id],
            ).fetchone()
            if not row:
                break
            suffix += 1
            vault_id = f"{base}_{suffix}"
        path = vault_file_path(uid, vault_id)
        _touch_duckdb_file(path)
        sysdb.execute(
            """
            INSERT INTO main.user_vaults (user_id, vault_id, vault_name, is_active)
            VALUES (?, ?, ?, FALSE)
            """,
            [uid, vault_id, name[:128]],
        )
        return {"vault_id": vault_id, "vault_name": name[:128], "db_path": str(path.resolve())}
    finally:
        sysdb.close()


def switch_vault(user_id: Any, vault_id: str) -> bool:
    uid = _safe_user_id(user_id)
    vid = _slug_vault_id(vault_id)
    if not vid:
        return False
    ensure_registry()
    sysdb = duckdb.connect(str(system_db_path()), read_only=False)
    try:
        _sync_registry_with_files(sysdb, uid)
        exists = sysdb.execute(
            "SELECT 1 FROM main.user_vaults WHERE user_id = ? AND vault_id = ? LIMIT 1",
            [uid, vid],
        ).fetchone()
        if not exists:
            return False
        _touch_duckdb_file(vault_file_path(uid, vid))
        sysdb.execute("UPDATE main.user_vaults SET is_active = FALSE WHERE user_id = ?", [uid])
        sysdb.execute(
            "UPDATE main.user_vaults SET is_active = TRUE WHERE user_id = ? AND vault_id = ?",
            [uid, vid],
        )
        return True
    finally:
        sysdb.close()


def remove_vault(user_id: Any, vault_id: str) -> bool:
    uid = _safe_user_id(user_id)
    vid = _slug_vault_id(vault_id)
    if not vid:
        return False
    ensure_registry()
    sysdb = duckdb.connect(str(system_db_path()), read_only=False)
    was_active = False
    try:
        row = sysdb.execute(
            "SELECT is_active FROM main.user_vaults WHERE user_id = ? AND vault_id = ? LIMIT 1",
            [uid, vid],
        ).fetchone()
        if not row:
            return False
        was_active = bool(row[0])
        sysdb.execute("DELETE FROM main.user_vaults WHERE user_id = ? AND vault_id = ?", [uid, vid])
    finally:
        sysdb.close()
    try:
        vault_file_path(uid, vid).unlink(missing_ok=True)
    except Exception:
        pass
    if was_active:
        _bootstrap_default_if_missing(uid)
    return True


def validate_user_db_path(user_id: Any, db_path: str) -> bool:
    uid = _safe_user_id(user_id)
    root = user_vault_dir(uid).resolve()
    path = Path(db_path).resolve()
    try:
        path.relative_to(root)
        return path.suffix.lower() == ".duckdb"
    except Exception:
        return False
