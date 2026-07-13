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

def test_schema_md_does_not_repeat_the_false_claims(tmp_path):
    """SCHEMA.md 里的每句话都是 C 阶段唯一的信息来源,**假话比缺话更糟**。
    这几条曾经是假的,别让它们漂回来。"""
    scaffold(tmp_path, "box1", Writer())
    s = (tmp_path / "SCHEMA.md").read_text(encoding="utf-8")

    # §11.2:非 git 的插件仓是**整个跳过**,不是"退化成整棵目录拷贝"(那只对 skill 成立)
    assert "整个跳过" in s
    assert "git init" in s               # …后果:手写的非 git 插件根本没进备份
    # §9:被铲的是 plugins/<仓名>/,不是整个 plugins/;且快照只增不减
    assert "只增不减" in s
    # §5/§1:刚建的金库里没有 MEMORY.md
    assert "不存在 = 空" in s
    # §2:引号剥一层、行内注释不剥、布尔必须是真布尔
    assert "剥一层配对的外层引号" in s
    assert "行内注释**不剥**" in s
    assert "必须是**真布尔**" in s
    # §8:codex 的 plugins.toml 永远没有 [repos.*]
    assert "永远没有** `[repos.*]`" in s

    # ---- 最终评审补的几条(2026-07-13)----

    # §10(finding 7):曾经写着加新设备时"已有的东西一个字节都不动" —— 假的,
    # scaffold **无条件重写 SCHEMA.md**。而且这条假话背后有个真坑:老版本的 hub
    # 往新金库里 scaffold,会把契约静默降级。
    assert "一个字节都不动" not in s          # 那句假话不许漂回来
    assert "静默降级" in s

    # §3(finding 1):配了但路径不存在 = 配置错误 → 抛错中止,不是"工具没装"
    assert "路径不存在" in s
    assert "抛错中止" in s

    # §8/§12(finding 2):hooks 写不出来只跳过那一张表,不再让整份 collect 暴毙
    assert "被跳过" in s

    # §2(finding 4):提取器不认识的键原样带着走
    assert "原样带着走" in s
    assert "originSessionId" in s

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


# ---- 多设备:往已有金库里加一台新机,不该被逼着用 --force --------------------

def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}

def test_adding_a_second_device_needs_no_force(tmp_path):
    """真实的多设备流程:clone 一个已有金库,再给本机 scaffold 一份 device.toml。
    这不是"往陌生目录里乱倒",也没有覆盖任何人的配置——不该要 --force。"""
    scaffold(tmp_path, "box1", Writer())
    # box1 已经用起来了:填好的 device.toml、手工整理的豁免名单、共享区的记忆
    dev1 = tmp_path / "box1" / "device.toml"
    dev1.write_text("class = [\"work\"]\n[paths]\nVAULT = \"D:/已经填好的\"\n", encoding="utf-8")
    exempt = tmp_path / "lint-exempt.txt"
    exempt.write_text("# 我手工整理的\nreference_dev_toolchain_local\n", encoding="utf-8")
    mem = tmp_path / "shared" / "memory" / "m.md"
    mem.write_text("---\nname: m\n---\n正文\n", encoding="utf-8")
    before = _snapshot(tmp_path)

    scaffold(tmp_path, "box2", Writer())          # 新机加入,不带 --force

    assert (tmp_path / "box2" / "device.toml").is_file()
    after = _snapshot(tmp_path)
    # 别人的东西、用户手工维护的东西,一个字节都不许动
    for key in ("box1/device.toml", "lint-exempt.txt", "shared/memory/m.md"):
        assert after[key] == before[key], key
    for key in before:
        if key != "SCHEMA.md":                    # SCHEMA.md 是派生物,本来就该重写
            assert after[key] == before[key], key

def test_re_scaffolding_the_same_host_still_refuses(tmp_path):
    """原来的数据丢失 bug:重跑同一台机,把手填的源路径静默换回占位符。照旧拒绝。"""
    scaffold(tmp_path, "box1", Writer())
    dev = tmp_path / "box1" / "device.toml"
    dev.write_text("class = [\"real\"]\n[paths]\nVAULT = \"D:/已经填好的\"\n", encoding="utf-8")
    before = dev.read_bytes()

    with pytest.raises(VaultNotEmptyError) as e:
        scaffold(tmp_path, "box1", Writer())

    assert "box1" in str(e.value) and "device.toml" in str(e.value)
    assert dev.read_bytes() == before

def test_non_empty_non_vault_dir_still_refuses(tmp_path):
    """目标非空、又不是金库(没有 vault.toml)——别往陌生目录里乱倒。"""
    (tmp_path / "别人的文件.txt").write_text("x", encoding="utf-8")

    with pytest.raises(VaultNotEmptyError) as e:
        scaffold(tmp_path, "box1", Writer())

    assert "vault.toml" in str(e.value)

def test_a_bare_git_init_dir_is_treated_as_empty(tmp_path):
    """`git init && scaffold` 不该被 .git 这一个条目逼进 --force。"""
    (tmp_path / ".git").mkdir()

    scaffold(tmp_path, "box1", Writer())          # 不带 --force

    assert (tmp_path / "vault.toml").is_file()

def test_force_does_not_wipe_the_curated_lint_exempt(tmp_path):
    """lint-exempt.txt 是用户手工整理的。--force 也不许把它清回空模板——
    清了之后下一次 hub sync 会在那些原本豁免的记忆上跪掉。"""
    scaffold(tmp_path, "box1", Writer())
    exempt = tmp_path / "lint-exempt.txt"
    exempt.write_text("# 我手工整理的\nreference_dev_toolchain_local\n", encoding="utf-8")
    before = exempt.read_bytes()

    scaffold(tmp_path, "box1", Writer(), force=True)

    assert exempt.read_bytes() == before

def test_force_does_not_downgrade_vault_toml(tmp_path):
    """vault.toml 是金库的格式版本标记,建库那台机写的。别的机器再跑 scaffold
    不许把它写回 version = 1——那是撒谎式降级。"""
    scaffold(tmp_path, "box1", Writer())
    cfg = tmp_path / "vault.toml"
    cfg.write_text("version = 2\n", encoding="utf-8")

    scaffold(tmp_path, "box2", Writer(), force=True)

    assert cfg.read_text(encoding="utf-8") == "version = 2\n"

def test_schema_md_is_always_rewritten(tmp_path):
    """SCHEMA.md 是从代码派生的契约文本,每次都该重写成当前版本。"""
    scaffold(tmp_path, "box1", Writer())
    (tmp_path / "SCHEMA.md").write_text("过时的内容\n", encoding="utf-8")

    scaffold(tmp_path, "box2", Writer())

    assert "金库 SCHEMA" in (tmp_path / "SCHEMA.md").read_text(encoding="utf-8")
