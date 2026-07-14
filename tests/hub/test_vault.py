import pytest
from pathlib import Path
from hub.vault import load_vault, load_device, memory_dirs
from hub.model import SHARED

_MEM = """---
name: {n}
description: {n} 的摘要
metadata:
  type: reference
  scope: [global]
---
正文
"""

def _mk(root: Path, host: str = "box1"):
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / SHARED / "memory").mkdir(parents=True)
    (root / SHARED / "memory" / "s1.md").write_text(_MEM.format(n="s1"), encoding="utf-8")
    (root / host / "claude" / "memory").mkdir(parents=True)
    (root / host / "claude" / "memory" / "m1.md").write_text(_MEM.format(n="m1"), encoding="utf-8")
    (root / host / "device.toml").write_text(
        'class = ["work"]\n'
        'projects = ["xinao"]\n'
        "\n[paths]\nCLAUDE_HOME = \"C:/x/.claude\"\n"
        "\n[sources.claude]\n"
        'memory = ["C:/x/.claude/projects/p/memory"]\n'
        'skills = "C:/x/.claude/skills"\n'
        'plugin_repos = "C:/x/.claude/plugins-dev"\n'
        'settings = "C:/x/.claude/settings.json"\n'
        "\n[sources.codex]\n"
        'skills = "C:/x/.codex/skills"\n'
        'settings = "C:/x/.codex/config.toml"\n'
        'agents = "C:/x/.codex/AGENTS.md"\n',
        encoding="utf-8")
    return root

def test_memory_dirs_covers_shared_and_each_device(tmp_path):
    _mk(tmp_path)
    got = {origin: d.name for origin, d in memory_dirs(tmp_path)}
    assert got == {SHARED: "memory", "box1": "memory"}

def test_load_vault_tags_origin(tmp_path):
    _mk(tmp_path)
    v = load_vault(tmp_path)
    assert {m.name: m.origin for m in v.memories} == {"s1": SHARED, "m1": "box1"}

def test_device_sources_split_by_tool(tmp_path):
    _mk(tmp_path)
    dev = load_device(tmp_path, "box1")
    assert dev.classes == ["work"]
    assert dev.sources["claude"].skills == "C:/x/.claude/skills"
    assert dev.sources["claude"].memory == ["C:/x/.claude/projects/p/memory"]
    assert dev.sources["codex"].agents == "C:/x/.codex/AGENTS.md"
    assert dev.sources["codex"].plugin_repos is None      # Codex 没有自己写的插件

def test_device_without_codex_section(tmp_path):
    _mk(tmp_path)
    (tmp_path / "box1" / "device.toml").write_text(
        'class = []\nprojects = []\n[sources.claude]\nskills = "C:/x/.claude/skills"\n',
        encoding="utf-8")
    dev = load_device(tmp_path, "box1")
    assert "codex" not in dev.sources                     # 没装的工具就是没有，不是错误
