import pytest
from pathlib import Path
from hub.memview import collect_view_entries, ViewScopeError
from hub.model import DeviceProfile

def _shared_mem(vault, name, scope):
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} desc\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\nbody of {name}\n", encoding="utf-8")

def _vault_toml(vault):
    (vault / "vault.toml").write_text("version = 2\n", encoding="utf-8")

def _dev(classes=(), projects=()):
    return DeviceProfile(host="box", classes=list(classes), projects=list(projects),
                         paths={}, sources={})

def test_global_goes_to_every_tool(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[global]")
    names = [e.name for e in collect_view_entries(tmp_path, _dev(), "codex")]
    assert names == ["a"]

def test_tool_filter(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[tool:claude]")
    assert [e.name for e in collect_view_entries(tmp_path, _dev(), "claude")] == ["a"]
    assert collect_view_entries(tmp_path, _dev(), "codex") == []

def test_project_subscription(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[project:xinao]")
    assert collect_view_entries(tmp_path, _dev(projects=["xinao"]), "claude")[0].name == "a"
    assert collect_view_entries(tmp_path, _dev(projects=["other"]), "claude") == []

def test_illegal_scope_anywhere_aborts_before_any_entry(tmp_path):
    _vault_toml(tmp_path)
    _shared_mem(tmp_path, "a", "[global]")
    _shared_mem(tmp_path, "b", "[projet:xinao]")       # 手误
    with pytest.raises(ViewScopeError) as ei:
        collect_view_entries(tmp_path, _dev(), "claude")
    assert "b" in str(ei.value)                          # 点名文件

def test_entry_has_absolute_source(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[global]")
    e = collect_view_entries(tmp_path, _dev(), "claude")[0]
    assert e.source.is_absolute() and e.source.name == "a.md"
    assert e.description == "a desc"

def test_scan_ignores_device_memory(tmp_path):
    # 设备区放一条坏记忆——只扫 shared 就不该碰它（若走 load_vault 会被它炸到）
    from hub.memview import load_shared_memories
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[global]")
    dd = tmp_path / "box" / "claude" / "memory"; dd.mkdir(parents=True)
    (dd / "bad.md").write_text("not frontmatter at all", encoding="utf-8")
    assert [m.name for m in load_shared_memories(tmp_path)] == ["a"]

def test_shared_memory_container_escape_raises(tmp_path):
    from hub.memview import load_shared_memories, SharedMemoryError
    from hub.fslink import make_dir_link
    _vault_toml(tmp_path)
    outside = tmp_path / "out"; outside.mkdir()
    make_dir_link(outside, tmp_path / "shared")     # shared 父目录逃逸、shared/memory 尚不存在
    with pytest.raises(SharedMemoryError):
        load_shared_memories(tmp_path)

def test_stem_must_equal_name(tmp_path):
    from hub.memview import load_shared_memories, SharedMemoryError
    _vault_toml(tmp_path)
    d = tmp_path / "shared" / "memory"; d.mkdir(parents=True)
    (d / "wrongfile.md").write_text(          # 文件名 wrongfile，frontmatter name=a
        "---\nname: a\ndescription: x\nmetadata:\n  type: reference\n  scope: [global]\n---\n\nb\n",
        encoding="utf-8")
    with pytest.raises(SharedMemoryError):
        load_shared_memories(tmp_path)
