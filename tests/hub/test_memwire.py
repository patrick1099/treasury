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

def _backup_mem(vault, host, name):
    # 备份区 <host>/claude/memory/<name>.md（提升到 shared 之前记忆待在这里）
    d = vault / host / "claude" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name}d\nmetadata:\n  type: reference\n"
        f"  scope: [global]\n---\n\nbody\n", encoding="utf-8")

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

def test_warns_when_shared_empty_but_backup_has_memories(tmp_path, monkeypatch):
    # 发现①：shared/memory 空但本机备份区有记忆 → 提示先 promote，别静默给出空占位视图
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    _backup_mem(tmp_path, "box", "a")           # 备份区 1 条
    _backup_mem(tmp_path, "box", "b")           # 备份区 2 条；shared 仍空
    writes, warnings, plan = prepare_memory_views(tmp_path, _dev(tmp_path))
    assert any("备份区有 2 条" in w and "shared/memory 为空" in w
               and "promote-memory" in w for w in warnings)

def test_no_empty_warn_when_shared_nonempty(tmp_path, monkeypatch):
    # shared 非空 → 不该有空占位警告（即便备份区也有）
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    _backup_mem(tmp_path, "box", "a")
    writes, warnings, plan = prepare_memory_views(tmp_path, _dev(tmp_path))
    assert not any("shared/memory 为空" in w for w in warnings)

def test_no_empty_warn_on_fresh_machine_backup_also_empty(tmp_path, monkeypatch):
    # 全新机：shared 空 + 备份区也空（合法状态）→ 不警告，免噪音
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    writes, warnings, plan = prepare_memory_views(tmp_path, _dev(tmp_path))
    assert not any("shared/memory 为空" in w for w in warnings)

def test_empty_shared_warning_does_not_change_writes_or_raise(tmp_path, monkeypatch):
    # 只加 warning：写清单照常（3 视图 + CLAUDE.md + AGENTS.md），不抛、不改写入语义
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    _backup_mem(tmp_path, "box", "a")
    writes, warnings, plan = prepare_memory_views(tmp_path, _dev(tmp_path))
    paths = [p.name for p, _ in writes]
    assert paths.count("MEMORY.md") == 3 and "CLAUDE.md" in paths and "AGENTS.md" in paths

def test_opencode_default_path_untouched_without_explicit_optin(tmp_path, monkeypatch):
    # 用户决策：仅设备显式设 OPENCODE_CONFIG 才接 opencode。默认路径 ~/.config/opencode/
    # opencode.json 恰好存在（且带密钥）也绝不碰它——不 plan、不写、不 warn。
    # （HOME 已被 conftest 沙箱到 tmp，这里在沙箱 home 里造默认路径文件。）
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    dev = DeviceProfile(host="box", classes=[], projects=[], paths={   # 无 OPENCODE_CONFIG
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "CODEX_HOME": (tmp_path / ".codex").as_posix(),
    }, sources={})
    default_cfg = Path.home() / ".config" / "opencode" / "opencode.json"
    default_cfg.parent.mkdir(parents=True, exist_ok=True)
    default_cfg.write_text('{"model": "x"}', encoding="utf-8")
    writes, warnings, plan = prepare_memory_views(tmp_path, dev)
    assert plan is None                                            # 没接 opencode
    assert not any("opencode" in w for w in warnings)
    wire_memory_views(tmp_path, dev, Writer())
    assert default_cfg.read_text(encoding="utf-8") == '{"model": "x"}'   # 一个字节没动
    assert (hub_views_home() / "claude" / "MEMORY.md").exists()    # 其余照常
