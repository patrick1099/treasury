# sync 不写工具地盘：--refresh 缺省时只提示。用 monkeypatch 把 GitBackend/lint 短路，
# 断言 sync 成功路径不触碰 CLAUDE.md/AGENTS.md（工具地盘）。
from pathlib import Path
import hub.cli as cli

def test_sync_does_not_write_tool_dirs(tmp_path, monkeypatch, capsys):
    # 构造最小金库；sync 只应写 MEMORY.md（金库内），不写任何 ~/.claude 之类
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (tmp_path / "shared" / "memory").mkdir(parents=True)
    class _B:
        def __init__(self, *a): pass
        def acquire(self): pass
        def publish(self, *a): pass
        def status(self): return ""
    monkeypatch.setattr(cli, "GitBackend", _B)
    rc = cli.main(["sync", "--vault", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / ".claude").exists()
