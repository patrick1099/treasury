from pathlib import Path
from hub.model import DeviceProfile
from hub.writer import Writer
from hub.status_report import view_health
from hub.memwire import wire_memory_views

def _dev(tmp_path):
    return DeviceProfile(host="b", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "CODEX_HOME": (tmp_path / ".codex").as_posix()}, sources={})

def _mem(vault, name, body="body"):
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n  scope: [global]\n---\n\n{body}\n",
        encoding="utf-8")

def test_flags_missing_before_register(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _mem(tmp_path, "a")
    rows = view_health(tmp_path, _dev(tmp_path), tmp_path / "repo")
    assert any(state != "ok" for state, _ in rows)       # config/视图/链接都还没有

def test_flags_stale_after_shared_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _mem(tmp_path, "a", body="v1")
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())   # 生成视图（嵌当时哈希）
    _mem(tmp_path, "a", body="v2 changed")                  # shared 变了但没 refresh
    rows = view_health(tmp_path, _dev(tmp_path), tmp_path / "repo")
    assert any(state == "stale" for state, _ in rows)       # 新鲜度被识破
