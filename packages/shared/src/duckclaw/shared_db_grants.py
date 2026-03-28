"""
ACL: qué usuarios pueden usar rutas .duckdb compartidas (además de validate_user_db_path).

Spec: extensión Telegram Guard — permisos por base compartida.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional


def _query_all_dicts(db: Any, sql: str) -> list[dict[str, Any]]:
    if hasattr(db, "query"):
        try:
            raw = db.query(sql)
            if isinstance(raw, str):
                data = json.loads(raw) if raw.strip() else []
                return data if isinstance(data, list) else []
            if raw is not None:
                try:
                    desc = getattr(raw, "description", None)
                    if desc:
                        colnames = [d[0] for d in desc]
                        return [dict(zip(colnames, row)) for row in raw.fetchall()]
                except Exception:
                    pass
                try:
                    return raw.df().to_dict("records")
                except Exception:
                    pass
        except Exception:
            pass
    try:
        cur = db.execute(sql)
        colnames = [d[0] for d in (getattr(cur, "description", None) or [])]
        if colnames and hasattr(cur, "fetchall"):
            return [dict(zip(colnames, row)) for row in (cur.fetchall() or [])]
    except Exception:
        pass
    return []


_USER_SHARED_DB_ACCESS_DDL = """
CREATE TABLE IF NOT EXISTS main.user_shared_db_access (
    tenant_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, user_id, resource_key)
);
"""

_RESOURCE_KEY_RE = re.compile(r"^[a-z0-9_*][a-z0-9_*-]{0,63}$", re.IGNORECASE)


def ensure_user_shared_db_access_table(db: Any) -> None:
    db.execute(_USER_SHARED_DB_ACCESS_DDL)


def _sql_lit(v: str, max_len: int = 256) -> str:
    return (v or "").replace("'", "''")[:max_len]


def resolve_shared_resource_path(resource_key: str) -> Optional[str]:
    """
    Resuelve resource_key a ruta .duckdb.
    - 'default' -> DUCKCLAW_SHARED_DB_PATH
    - '*' -> None (comodín, no se compara por ruta)
    - otro -> DUCKCLAW_SHARED_RESOURCE_<KEY> con KEY en MAYÚSCULAS y guiones -> _
    """
    rk = (resource_key or "").strip().lower()
    if rk in ("*", ""):
        return None
    if rk == "default":
        p = (os.environ.get("DUCKCLAW_SHARED_DB_PATH") or "").strip()
        return p or None
    env_suffix = rk.upper().replace("-", "_")
    p = (os.environ.get(f"DUCKCLAW_SHARED_RESOURCE_{env_suffix}") or "").strip()
    return p or None


def normalize_resolved_path(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def user_may_access_shared_path(
    acl_db: Any,
    *,
    tenant_id: str,
    user_id: str,
    shared_db_path: str,
) -> bool:
    """
    True si la ruta compartida está permitida para el usuario en este tenant.

    1) Debe pasar validate_user_db_path (sandbox físico).
    2) Si no hay filas en user_shared_db_access para (tenant_id, user_id),
       se mantiene compatibilidad: basta con (1).
    3) Si hay filas: debe existir comodín '*' o un resource_key cuya ruta
       resuelta coincida con shared_db_path (mismo path canónico).
    """
    from duckclaw.vaults import validate_user_db_path

    tid = str(tenant_id or "").strip() or "default"
    uid = str(user_id or "").strip() or "default"
    path = (shared_db_path or "").strip()
    if not path or Path(path).suffix.lower() != ".duckdb":
        return False
    if not validate_user_db_path(uid, path, tenant_id=tid):
        return False

    ensure_user_shared_db_access_table(acl_db)
    tid_sql = _sql_lit(tid, 128)
    uid_sql = _sql_lit(uid, 128)
    sql = (
        f"SELECT resource_key FROM main.user_shared_db_access "
        f"WHERE tenant_id='{tid_sql}' AND user_id='{uid_sql}'"
    )
    rows: list[Any] = _query_all_dicts(acl_db, sql)

    if not rows:
        return True

    try:
        want = normalize_resolved_path(path)
    except Exception:
        want = path

    for r in rows:
        if not isinstance(r, dict):
            continue
        key = str(r.get("resource_key") or "").strip()
        if key == "*":
            return True
        resolved = resolve_shared_resource_path(key)
        if not resolved:
            continue
        try:
            if normalize_resolved_path(resolved) == want:
                return True
        except Exception:
            if os.path.abspath(resolved) == os.path.abspath(path):
                return True
    return False


def validate_resource_key(resource_key: str) -> bool:
    return bool(_RESOURCE_KEY_RE.match((resource_key or "").strip()))


def path_is_under_shared_tree(db_path: str) -> bool:
    """True si la ruta cae bajo db/shared/ (árbol de bases compartidas)."""
    from duckclaw.vaults import db_root

    try:
        p = Path(db_path).expanduser().resolve()
        root = (db_root() / "shared").resolve()
        p.relative_to(root)
        return True
    except Exception:
        return False


def list_shared_grants_for_user(db: Any, *, tenant_id: str, user_id: str) -> list[dict[str, str]]:
    ensure_user_shared_db_access_table(db)
    tid_sql = _sql_lit(str(tenant_id or "default").strip() or "default", 128)
    uid_sql = _sql_lit(str(user_id or "").strip(), 128)
    rows = _query_all_dicts(
        db,
        f"SELECT user_id, resource_key, created_at FROM main.user_shared_db_access "
        f"WHERE tenant_id='{tid_sql}' AND user_id='{uid_sql}' ORDER BY resource_key",
    )
    out: list[dict[str, str]] = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(
                {
                    "user_id": str(r.get("user_id") or ""),
                    "resource_key": str(r.get("resource_key") or ""),
                    "created_at": str(r.get("created_at") or ""),
                }
            )
    return out


def list_shared_grants_for_tenant(db: Any, *, tenant_id: str) -> list[dict[str, str]]:
    ensure_user_shared_db_access_table(db)
    tid_sql = _sql_lit(str(tenant_id or "default").strip() or "default", 128)
    rows = _query_all_dicts(
        db,
        f"SELECT user_id, resource_key, created_at FROM main.user_shared_db_access "
        f"WHERE tenant_id='{tid_sql}' ORDER BY user_id, resource_key",
    )
    out: list[dict[str, str]] = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(
                {
                    "user_id": str(r.get("user_id") or ""),
                    "resource_key": str(r.get("resource_key") or ""),
                    "created_at": str(r.get("created_at") or ""),
                }
            )
    return out


def upsert_shared_grant(db: Any, *, tenant_id: str, user_id: str, resource_key: str) -> None:
    ensure_user_shared_db_access_table(db)
    tid = _sql_lit(str(tenant_id or "default").strip() or "default", 128)
    uid = _sql_lit(str(user_id or "").strip(), 128)
    rk = _sql_lit(str(resource_key or "").strip().lower(), 64)
    db.execute(
        f"""
        INSERT INTO main.user_shared_db_access (tenant_id, user_id, resource_key)
        VALUES ('{tid}', '{uid}', '{rk}')
        ON CONFLICT (tenant_id, user_id, resource_key) DO UPDATE SET
          created_at = now()
        """
    )


def delete_shared_grant(db: Any, *, tenant_id: str, user_id: str, resource_key: str) -> None:
    ensure_user_shared_db_access_table(db)
    tid = _sql_lit(str(tenant_id or "default").strip() or "default", 128)
    uid = _sql_lit(str(user_id or "").strip(), 128)
    rk = _sql_lit(str(resource_key or "").strip().lower(), 64)
    db.execute(
        f"DELETE FROM main.user_shared_db_access "
        f"WHERE tenant_id='{tid}' AND user_id='{uid}' AND resource_key='{rk}'"
    )
