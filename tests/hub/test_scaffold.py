import tomllib
from pathlib import Path
from hub.scaffold_vault import scaffold
from hub.writer import Writer
from hub.vault import load_vault, load_device

def test_scaffold_creates_both_zones(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    for p in ["vault.toml", "SCHEMA.md",
              "shared/memory", "shared/skills", "shared/plugins",
              "shared/hooks", "shared/chats",
              "box1/device.toml",
              "box1/claude/memory", "box1/claude/skills", "box1/claude/plugins",
              "box1/claude/hooks", "box1/claude/chats",
              "box1/codex/skills", "box1/codex/hooks", "box1/codex/chats"]:
        assert (tmp_path / p).exists(), p

def test_placeholder_dirs_have_gitkeep(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    assert (tmp_path / "shared" / "chats" / ".gitkeep").exists()
    assert (tmp_path / "box1" / "claude" / "hooks" / ".gitkeep").exists()

def test_scaffolded_vault_loads(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    v = load_vault(tmp_path)
    assert v.memories == []
    dev = load_device(tmp_path, "box1")
    assert dev.host == "box1"

def test_device_toml_is_valid_toml_with_tool_sections(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    raw = tomllib.loads((tmp_path / "box1" / "device.toml").read_text(encoding="utf-8"))
    assert "claude" in raw["sources"] and "codex" in raw["sources"]

def test_schema_md_documents_the_contract(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    s = (tmp_path / "SCHEMA.md").read_text(encoding="utf-8")
    for token in ["备份区", "共享区", "merged.txt", "rejected.txt",
                  "sensitive", "scope", "生成态"]:
        assert token in s, token

def test_dry_run_creates_nothing(tmp_path):
    scaffold(tmp_path, "box1", Writer(dry_run=True))
    assert not (tmp_path / "vault.toml").exists()
