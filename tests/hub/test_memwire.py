import pytest
from pathlib import Path
from hub.writer import Writer
from hub.model import DeviceProfile
from hub.memwire import wire_memory_views, prepare_memory_views, hub_views_home
from hub.textblock import BEGIN, END, BlockError

def _dev(tmp_path):
    return DeviceProfile(host="box", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "CODEX_HOME": (tmp_path / ".codex").as_posix(),
        "OPENCODE_CONFIG": (tmp_path / "opencode.json").as_posix(),
    }, sources={})

def _shared_mem(vault, name, scope):
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name}d\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\nbody\n", encoding="utf-8")

def test_wires_three_views_and_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert (hub_views_home() / "claude" / "MEMORY.md").exists()
    assert (hub_views_home() / "codex" / "MEMORY.md").exists()
    claude_md = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "hub:begin" in claude_md and "@" in claude_md   # Claude @import 指针
    assert "`a`" in (tmp_path / ".codex" / "AGENTS.md").read_text(encoding="utf-8")  # Codex 内联

def test_codex_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "AGENTS.override.md").write_text("my override\n", encoding="utf-8")
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert "hub:begin" in (tmp_path / ".codex" / "AGENTS.override.md").read_text(encoding="utf-8")
    assert not (tmp_path / ".codex" / "AGENTS.md").exists()  # 没写被遮蔽的那份

def test_deterministic_error_leaves_no_partial_views(tmp_path, monkeypatch):
    # #2 关键回归：CLAUDE.md 里有坏受管块（重复标记）→ 预检期抛 BlockError、三份视图一个都不该落
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    claude = tmp_path / ".claude"; claude.mkdir()
    (claude / "CLAUDE.md").write_text(f"{BEGIN}\nx\n{END}\n{BEGIN}\ny\n{END}\n", encoding="utf-8")
    with pytest.raises(BlockError):
        wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert not (hub_views_home() / "claude" / "MEMORY.md").exists()   # 没留半套视图

def test_opencode_refuse_is_warning_not_failure(tmp_path, monkeypatch):
    # #5：opencode 是 JSONC → refuse 归 warnings，不抛、不阻断视图落盘
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text('{\n  // c\n}', encoding="utf-8")
    summary = wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert (hub_views_home() / "claude" / "MEMORY.md").exists()
    assert any("opencode" in x for x in summary["warnings"])

def test_commit_partial_then_rerun_converges(tmp_path, monkeypatch):
    # spec §9.7：提交期第 N 次写失败 → 可能部分完成、不回滚；重跑 wire 幂等收敛
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    real = Writer.write_text_atomic
    n = {"i": 0}
    def flaky(self, path, text):
        n["i"] += 1
        if n["i"] == 2:                         # 第 2 次写（codex 视图）失败
            raise OSError("boom")
        return real(self, path, text)
    monkeypatch.setattr(Writer, "write_text_atomic", flaky)
    with pytest.raises(OSError):
        wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert (hub_views_home() / "claude" / "MEMORY.md").exists()   # 部分完成：第一份在
    monkeypatch.setattr(Writer, "write_text_atomic", real)         # 恢复正常
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())          # 重跑收敛
    for t in ("claude", "codex", "opencode"):
        assert (hub_views_home() / t / "MEMORY.md").exists()
    assert "hub:begin" in (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
