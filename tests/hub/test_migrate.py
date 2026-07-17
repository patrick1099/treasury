import pytest
from pathlib import Path
from hub.migrate import migrate_schema, SchemaMigrationError
from hub.writer import Writer

def _mk_vault(tmp_path, memories):
    (tmp_path / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    d = tmp_path / "shared" / "memory"; d.mkdir(parents=True)
    for name, scope in memories:
        (d / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n"
            f"  scope: {scope}\n---\n\nbody\n", encoding="utf-8")
    return tmp_path

def test_bumps_when_all_global(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]"), ("b", "[global]")])
    migrate_schema(v, 2, Writer())
    assert "version = 2" in (v / "vault.toml").read_text(encoding="utf-8")

def test_refuses_old_device_grammar(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]"), ("b", "[device:work]")])
    with pytest.raises(SchemaMigrationError) as ei:
        migrate_schema(v, 2, Writer())
    assert "b" in str(ei.value)
    assert "version = 1" in (v / "vault.toml").read_text(encoding="utf-8")  # 没升

def test_refuses_valid_but_nonglobal(tmp_path):
    # 即便是 v2 合法的 class:work，v1→v2 门槛也要求**全 global** → 拒绝、版本不动
    v = _mk_vault(tmp_path, [("a", "[global]"), ("c", "[class:work]")])
    with pytest.raises(SchemaMigrationError):
        migrate_schema(v, 2, Writer())
    assert "version = 1" in (v / "vault.toml").read_text(encoding="utf-8")

def test_refuses_when_not_v1(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]")])
    (v / "vault.toml").write_text("version = 2\n", encoding="utf-8")  # 已是 v2
    with pytest.raises(SchemaMigrationError):
        migrate_schema(v, 2, Writer())

def test_dry_run_writes_nothing(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]")])
    migrate_schema(v, 2, Writer(dry_run=True))
    assert "version = 1" in (v / "vault.toml").read_text(encoding="utf-8")
