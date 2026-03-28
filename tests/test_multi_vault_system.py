from __future__ import annotations

from duckclaw.graphs.on_the_fly_commands import handle_command
from duckclaw.workers.manifest import WorkerSpec
from duckclaw.workers import factory as worker_factory
from duckclaw.vaults import (
    create_vault,
    list_vaults,
    remove_vault,
    resolve_active_vault,
    shared_tenant_dir,
    switch_vault,
    validate_user_db_path,
)


class _DummyDB:
    def execute(self, *_args, **_kwargs):
        return None

    def query(self, *_args, **_kwargs):
        return "[]"


def test_resolve_active_vault_bootstraps_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    vault_id, db_path = resolve_active_vault("1726618406")
    assert vault_id == "default"
    assert db_path.endswith("default.duckdb")


def test_create_switch_remove_vault_cycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _ = resolve_active_vault("user1")
    created = create_vault("user1", "inversiones")
    assert created["vault_id"].startswith("inversiones")
    assert switch_vault("user1", created["vault_id"]) is True
    active_id, active_path = resolve_active_vault("user1")
    assert active_id == created["vault_id"]
    assert validate_user_db_path("user1", active_path) is True
    assert remove_vault("user1", created["vault_id"]) is True
    active_id_after, _ = resolve_active_vault("user1")
    assert active_id_after == "default"


def test_vault_command_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _DummyDB()
    out = handle_command(db, "chat1", "/vault", requester_id="u1", tenant_id="default", vault_user_id="u1")
    assert out and "Bóveda activa" in out
    out = handle_command(db, "chat1", "/vault new trabajo", requester_id="u1", tenant_id="default", vault_user_id="u1")
    assert out and "Bóveda creada" in out
    rows = list_vaults("u1")
    target = [r for r in rows if r["vault_id"] != "default"][0]["vault_id"]
    out = handle_command(db, "chat1", f"/vault use {target}", requester_id="u1", tenant_id="default", vault_user_id="u1")
    assert out and "activa actual" in out


def test_resolve_promotes_existing_non_default_when_default_active(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = "1726618406"
    # Bootstraps default as active
    _ = resolve_active_vault(user)
    # Create a larger real vault file manually (simulate prior data)
    private_dir = tmp_path / "db" / "private" / user
    private_dir.mkdir(parents=True, exist_ok=True)
    real_vault = private_dir / "finanzdb1.duckdb"
    real_vault.write_bytes(b"x" * 200_000)
    active_id, active_path = resolve_active_vault(user)
    assert active_id == "finanzdb1"
    assert active_path.endswith("finanzdb1.duckdb")


def test_validate_shared_paths_user_and_tenant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = "u-shared"
    tenant = "Leila Store"
    private_dir = tmp_path / "db" / "private" / user
    private_dir.mkdir(parents=True, exist_ok=True)
    shared_user = tmp_path / "db" / "shared" / user
    shared_user.mkdir(parents=True, exist_ok=True)
    tid_slug = "leila_store"
    shared_tenant = tmp_path / "db" / "shared" / tid_slug
    shared_tenant.mkdir(parents=True, exist_ok=True)
    p_private = private_dir / "x.duckdb"
    p_private.write_bytes(b"x")
    p_su = shared_user / "a.duckdb"
    p_su.write_bytes(b"x")
    p_st = shared_tenant / "cat.duckdb"
    p_st.write_bytes(b"x")

    assert validate_user_db_path(user, str(p_private.resolve())) is True
    assert validate_user_db_path(user, str(p_su.resolve())) is True
    assert validate_user_db_path(user, str(p_st.resolve())) is False
    assert validate_user_db_path(user, str(p_st.resolve()), tenant_id=tenant) is True
    assert validate_user_db_path(user, str(p_st.resolve()), tenant_id="other_tenant") is False


def test_resolve_shared_db_path_requires_manifest_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec = WorkerSpec(
        worker_id="w",
        name="W",
        schema_name="w",
        llm_required=None,
        temperature=0.2,
        topology="general",
        skills_list=[],
        allowed_tables=[],
        read_only=False,
        worker_dir=tmp_path,
        forge_shared_db_path_env="DUCKCLAW_SHARED_DB_PATH",
    )
    monkeypatch.delenv("DUCKCLAW_SHARED_DB_PATH", raising=False)
    assert worker_factory._resolve_shared_db_path(spec, None) is None
    monkeypatch.setenv("DUCKCLAW_SHARED_DB_PATH", str(tmp_path / "c.duckdb"))
    assert worker_factory._resolve_shared_db_path(spec, None) == str(tmp_path / "c.duckdb")
    assert worker_factory._resolve_shared_db_path(spec, "/override/path.duckdb") == "/override/path.duckdb"


def test_shared_tenant_dir_ensures_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = shared_tenant_dir("Acme Corp")
    assert d.is_dir()
    assert "shared" in d.parts
    assert "acme_corp" == d.name


def test_list_and_use_detect_files_not_pre_registered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    user = "u-detector"
    private_dir = tmp_path / "db" / "private" / user
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / "inversiones.duckdb").write_bytes(b"x" * 50_000)
    # list_vaults should discover filesystem vault and register it.
    rows = list_vaults(user)
    ids = {r["vault_id"] for r in rows}
    assert "inversiones" in ids
    assert switch_vault(user, "inversiones") is True
    active_id, _ = resolve_active_vault(user)
    assert active_id == "inversiones"
