# tests/hub/test_hub_memory_skill.py
from pathlib import Path

def test_skill_files_exist():
    root = Path(__file__).resolve().parents[2] / "hub" / "skills" / "hub-memory"
    assert (root / "SKILL.md").is_file()
    assert (root / "scripts" / "read_memory.py").is_file()

def test_skill_md_frontmatter():
    root = Path(__file__).resolve().parents[2] / "hub" / "skills" / "hub-memory"
    txt = (root / "SKILL.md").read_text(encoding="utf-8")
    assert txt.startswith("---")
    assert "name: hub-memory" in txt and "description:" in txt

def test_wrapper_delegates_not_reimplements():
    root = Path(__file__).resolve().parents[2] / "hub" / "skills" / "hub-memory"
    src = (root / "scripts" / "read_memory.py").read_text(encoding="utf-8")
    assert "hub.cli" in src and "memory-read" in src      # 只转调，不自己解析记忆
    assert "resolve_symbols" not in src                    # 核心逻辑不在包装里
