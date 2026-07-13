"""run_all() 汇总流水线的测试——尤其是 agents(CLAUDE.md / AGENTS.md)分支。

Finding 1 (task 11 review): agents 分支是全项目里唯一一处读源文件前不过
hub.guard.check_source() 硬闸的地方。collect/memory.py、skills.py、decl.py
的每个源读取前都调用它;agents 分支漏了,导致 [sources.claude] agents 指向
~/.claude/secrets/CLAUDE.md 时,密钥原文会被复制进金库。
"""
import pytest
from pathlib import Path
from hub.collect import run_all
from hub.guard import SecretPathError
from hub.model import DeviceProfile, ToolSources
from hub.writer import Writer


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    return tmp_path


def _dev(host: str, tool: str, agents_path: Path) -> DeviceProfile:
    return DeviceProfile(
        host=host, classes=[], projects=[], paths={},
        sources={tool: ToolSources(agents=str(agents_path))},
    )


def test_agents_file_is_collected_for_claude(tmp_path):
    v = _vault(tmp_path)
    agents = tmp_path / "home" / "CLAUDE.md"
    agents.parent.mkdir(parents=True)
    agents.write_text("我的全局约定\n", encoding="utf-8")
    run_all(v, _dev("box1", "claude", agents), Writer())
    out = v / "box1" / "claude" / "CLAUDE.md"
    assert out.read_text(encoding="utf-8") == "我的全局约定\n"


def test_agents_file_is_collected_for_codex(tmp_path):
    v = _vault(tmp_path)
    agents = tmp_path / "home" / "AGENTS.md"
    agents.parent.mkdir(parents=True)
    agents.write_text("codex 的全局约定\n", encoding="utf-8")
    run_all(v, _dev("box1", "codex", agents), Writer())
    out = v / "box1" / "codex" / "AGENTS.md"
    assert out.read_text(encoding="utf-8") == "codex 的全局约定\n"


def test_agents_under_secrets_is_refused_for_claude(tmp_path):
    v = _vault(tmp_path)
    agents = tmp_path / "home" / "secrets" / "CLAUDE.md"
    agents.parent.mkdir(parents=True)
    agents.write_text("token=super-secret\n", encoding="utf-8")
    with pytest.raises(SecretPathError):
        run_all(v, _dev("box1", "claude", agents), Writer())
    assert not (v / "box1" / "claude" / "CLAUDE.md").exists()
    leaked = [p for p in (v / "box1").rglob("*") if p.is_file()
              and "super-secret" in p.read_text(encoding="utf-8", errors="ignore")]
    assert leaked == []


def test_agents_under_secrets_is_refused_for_codex(tmp_path):
    v = _vault(tmp_path)
    agents = tmp_path / "home" / "secrets" / "AGENTS.md"
    agents.parent.mkdir(parents=True)
    agents.write_text("token=super-secret\n", encoding="utf-8")
    with pytest.raises(SecretPathError):
        run_all(v, _dev("box1", "codex", agents), Writer())
    assert not (v / "box1" / "codex" / "AGENTS.md").exists()
    leaked = [p for p in (v / "box1").rglob("*") if p.is_file()
              and "super-secret" in p.read_text(encoding="utf-8", errors="ignore")]
    assert leaked == []
