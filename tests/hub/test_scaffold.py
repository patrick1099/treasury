import tomllib
import pytest
from pathlib import Path
from hub.scaffold_vault import scaffold, VaultNotEmptyError
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
                  "sensitive", "scope", "生成态",
                  # C 阶段离了这几样就只能猜，猜错会静默毁掉记忆：
                  "device.toml",      # class 是判 device: scope 的唯一依据
                  "MEMORY.md",        # 索引，不然加载器会读全文撑爆上下文
                  "$CLAUDE_HOME",     # 符号根：正文里不许出现绝对路径
                  "lint-exempt.txt",  # 上面那条 lint 的逃生舱
                  "gethostname",      # <设备名> 怎么算出来的
                  ]:
        assert token in s, token

def test_dry_run_creates_nothing(tmp_path):
    scaffold(tmp_path, "box1", Writer(dry_run=True))
    # 断言到"一个条目都没有"这一层：只查 vault.toml 的话，scaffold 里偷摸加一句
    # 没过闸的 Path.mkdir 也照样绿——目录不是文件，但它一样是落盘。
    assert list(tmp_path.iterdir()) == []

def test_refuses_to_scaffold_over_a_non_empty_dir(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    dev = tmp_path / "box1" / "device.toml"
    dev.write_text("class = [\"real\"]\n[paths]\nVAULT = \"D:/已经填好的\"\n", encoding="utf-8")
    before = dev.read_bytes()

    with pytest.raises(VaultNotEmptyError):
        scaffold(tmp_path, "box1", Writer())

    assert dev.read_bytes() == before          # 用户手填的配置一个字节都没动

def test_force_overwrites_an_existing_vault(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    dev = tmp_path / "box1" / "device.toml"
    dev.write_text("class = [\"real\"]\n", encoding="utf-8")

    scaffold(tmp_path, "box1", Writer(), force=True)

    assert "<占位" in dev.read_text(encoding="utf-8") or "<金库路径>" in dev.read_text(encoding="utf-8")
