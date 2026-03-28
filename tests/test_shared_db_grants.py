from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_user_may_access_shared_path_no_rows_allows_when_path_valid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import duckdb
    from duckclaw.shared_db_grants import ensure_user_shared_db_access_table, user_may_access_shared_path

    acl = tmp_path / "acl.duckdb"
    db = duckdb.connect(str(acl))
    ensure_user_shared_db_access_table(db)
    shared_dir = tmp_path / "db" / "shared" / "u1"
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared_file = shared_dir / "c.duckdb"
    shared_file.write_bytes(b"x")
    monkeypatch.setenv("DUCKCLAW_REPO_ROOT", str(tmp_path))
    assert user_may_access_shared_path(
        db,
        tenant_id="default",
        user_id="u1",
        shared_db_path=str(shared_file.resolve()),
    )
    db.close()


def test_user_may_access_denied_when_grants_exist_and_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import duckdb
    from duckclaw.shared_db_grants import ensure_user_shared_db_access_table, upsert_shared_grant, user_may_access_shared_path

    acl = tmp_path / "acl.duckdb"
    db = duckdb.connect(str(acl))
    ensure_user_shared_db_access_table(db)
    shared_dir = tmp_path / "db" / "shared" / "u1"
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared_file = shared_dir / "c.duckdb"
    shared_file.write_bytes(b"x")
    monkeypatch.setenv("DUCKCLAW_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("DUCKCLAW_SHARED_DB_PATH", "/no/existe/leila.duckdb")
    upsert_shared_grant(db, tenant_id="Leila Store", user_id="u1", resource_key="default")
    assert not user_may_access_shared_path(
        db,
        tenant_id="Leila Store",
        user_id="u1",
        shared_db_path=str(shared_file.resolve()),
    )
    db.close()


def test_user_may_access_wildcard_grant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import duckdb
    from duckclaw.shared_db_grants import ensure_user_shared_db_access_table, upsert_shared_grant, user_may_access_shared_path

    acl = tmp_path / "acl.duckdb"
    db = duckdb.connect(str(acl))
    ensure_user_shared_db_access_table(db)
    shared_dir = tmp_path / "db" / "shared" / "u1"
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared_file = shared_dir / "c.duckdb"
    shared_file.write_bytes(b"x")
    monkeypatch.setenv("DUCKCLAW_REPO_ROOT", str(tmp_path))
    upsert_shared_grant(db, tenant_id="t1", user_id="u1", resource_key="*")
    assert user_may_access_shared_path(
        db,
        tenant_id="t1",
        user_id="u1",
        shared_db_path=str(shared_file.resolve()),
    )
    db.close()


def test_resolve_default_matches_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKCLAW_SHARED_DB_PATH", str(tmp_path / "x.duckdb"))
    from duckclaw.shared_db_grants import resolve_shared_resource_path

    assert Path(resolve_shared_resource_path("default") or "").name == "x.duckdb"
