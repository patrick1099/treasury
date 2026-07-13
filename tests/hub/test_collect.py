import subprocess
import pytest
from pathlib import Path
from hub.collect.errors import MissingSourceError
from hub.collect.memory import plan_memory, collect_memory
from hub.frontmatter import FrontmatterError
from hub.guard import SecretPathError
from hub.writer import Writer
from hub.model import SHARED

def _mem(d: Path, name: str, sensitive: bool = False, body: str = "正文\n"):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} 摘要\nmetadata:\n"
        f"  type: reference\n  scope: [global]\n"
        f"  sensitive: {'true' if sensitive else 'false'}\n---\n{body}",
        encoding="utf-8")

def _vault(tmp_path: Path, host: str = "box1") -> Path:
    (tmp_path / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / host / "claude" / "memory").mkdir(parents=True)
    (tmp_path / SHARED / "memory").mkdir(parents=True)
    return tmp_path

def test_collects_into_this_devices_claude_memory(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    _mem(src, "a")
    collect_memory([src], v, "box1", Writer())
    assert (v / "box1" / "claude" / "memory" / "a.md").exists()

def test_sensitive_is_never_collected(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    _mem(src, "secret_one", sensitive=True)
    r = collect_memory([src], v, "box1", Writer())
    assert not (v / "box1" / "claude" / "memory" / "secret_one.md").exists()
    assert r.skipped_sensitive == ["secret_one"]

def test_mirror_deletes_what_source_no_longer_has(tmp_path):
    v = _vault(tmp_path)
    stale = v / "box1" / "claude" / "memory" / "gone.md"
    stale.write_text("---\nname: gone\ndescription: d\n---\n旧\n", encoding="utf-8")
    src = tmp_path / "src"
    _mem(src, "a")
    r = collect_memory([src], v, "box1", Writer())
    assert r.deleted == ["gone"]
    assert not stale.exists()

def test_never_touches_shared_or_other_devices(tmp_path):
    v = _vault(tmp_path)
    (v / "box2" / "claude" / "memory").mkdir(parents=True)
    other = v / "box2" / "claude" / "memory" / "theirs.md"
    other.write_text("---\nname: theirs\ndescription: d\n---\n别人的\n", encoding="utf-8")
    sh = v / SHARED / "memory" / "pooled.md"
    sh.write_text("---\nname: pooled\ndescription: d\n---\n公共的\n", encoding="utf-8")
    before = (other.read_bytes(), sh.read_bytes())
    src = tmp_path / "src"
    _mem(src, "a")
    collect_memory([src], v, "box1", Writer())
    assert (other.read_bytes(), sh.read_bytes()) == before   # 逐字节不变

def test_broken_frontmatter_raises_not_silently_skipped(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.md").write_text("没有 frontmatter\n", encoding="utf-8")
    with pytest.raises(FrontmatterError, match="bad.md") as exc_info:
        collect_memory([src], v, "box1", Writer())
    # load_memory() already names the file; the collector must not wrap the
    # error a second time (that produced "...bad.md: ...bad.md: ..." before).
    msg = str(exc_info.value)
    assert msg.count("bad.md") == 1, f"file name should be prefixed exactly once, got: {msg!r}"

def test_secrets_source_is_refused(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(SecretPathError):
        collect_memory([tmp_path / ".claude" / "secrets"], v, "box1", Writer())

def test_no_source_configured_writes_nothing_and_deletes_nothing(tmp_path):
    """工具没装 = device.toml 里压根没有那个源 → 什么都不做,**尤其不是"源里空了"**。

    旧版这个测试只断言 r.written == [](还是对着一个**空**金库),r.deleted 碰都没碰,
    所以它在"把金库里的记忆全删光"这个行为下**照样通过**——一个没有牙齿的测试。
    这里先把金库填满,再断言删除集为空、文件逐字节还在。
    """
    v = _vault(tmp_path)
    home = v / "box1" / "claude" / "memory"
    for n in ("m1", "m2", "m3"):
        _mem(home, n)
    before = {p.name: p.read_bytes() for p in home.glob("*.md")}

    r = collect_memory([], v, "box1", Writer())      # 没有配任何记忆源

    assert r.written == [] and r.deleted == []
    assert {p.name: p.read_bytes() for p in home.glob("*.md")} == before

def test_configured_but_missing_source_refuses_and_deletes_nothing(tmp_path):
    """**配了、但那个目录不在** —— 这是配置错误,不是"用户把记忆全删了"。

    旧行为:_scan() 把它当"工具没装"跳过 → 源侧零条记忆 → _diff() 把金库里**每一条**
    记忆都算成 gone → collect_memory 全删。金库是这些记忆的**唯一备份**。
    scaffold --force 会把 <占位> 模板写回 device.toml,正好构成这个状态。
    """
    v = _vault(tmp_path)
    home = v / "box1" / "claude" / "memory"
    for n in ("m1", "m2", "m3"):
        _mem(home, n)
    before = {p.name: p.read_bytes() for p in home.glob("*.md")}

    missing = tmp_path / "nope" / "memory"
    with pytest.raises(MissingSourceError, match="nope"):
        collect_memory([missing], v, "box1", Writer())

    assert {p.name: p.read_bytes() for p in home.glob("*.md")} == before   # 一条都没删

def test_plan_also_refuses_configured_but_missing_source(tmp_path):
    """预览与实际必须同一套判断——plan 不能把"会删 3 条"这种谎话拿去问人。"""
    v = _vault(tmp_path)
    _mem(v / "box1" / "claude" / "memory", "m1")
    with pytest.raises(MissingSourceError):
        plan_memory([tmp_path / "nope"], v, "box1")

def test_empty_but_existing_source_still_mirror_deletes(tmp_path):
    """反向的牙齿:源目录**在**、只是里面没有记忆了 —— 那才是真的"用户删光了",
    镜像删除必须照常发生。修 finding 1 不能顺手把镜像语义一起阉掉。"""
    v = _vault(tmp_path)
    _mem(v / "box1" / "claude" / "memory", "m1")
    src = tmp_path / "src"
    src.mkdir()
    r = collect_memory([src], v, "box1", Writer())
    assert r.deleted == ["m1"]
    assert not (v / "box1" / "claude" / "memory" / "m1.md").exists()

def test_dry_run_writes_nothing(tmp_path):
    v = _vault(tmp_path)
    stale = v / "box1" / "claude" / "memory" / "gone.md"
    stale.write_text("---\nname: gone\ndescription: d\n---\n旧\n", encoding="utf-8")
    src = tmp_path / "src"
    _mem(src, "a")
    r = collect_memory([src], v, "box1", Writer(dry_run=True))
    assert r.written == ["a"] and r.deleted == ["gone"]     # 报告说会做什么
    assert not (v / "box1" / "claude" / "memory" / "a.md").exists()
    assert stale.exists()                                   # 但一个字节都没动

def test_plan_matches_what_collect_would_do(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    _mem(src, "a")
    p = plan_memory([src], v, "box1")
    r = collect_memory([src], v, "box1", Writer())
    assert (p.written, p.deleted) == (r.written, r.deleted)

def test_file_inside_legit_dir_that_resolves_into_secrets_is_denied(tmp_path):
    """Finding 2: the hard gate must apply to each individual file, not just
    the source directory root. A directory whose own literal path is clean
    (no 'secrets' component) can still contain an entry that — once resolved —
    lands inside secrets/. The scan must catch that at the per-file level.

    Real symlinks require elevation/Developer Mode on Windows (see
    test_guard.py::test_symlink_into_secrets_dir_is_denied, which skips on
    this class of machine). An NTFS junction (`mklink /J`) needs no elevation
    and resolves through the exact same Path.resolve() machinery, so it's
    used here as the on-disk reparse-point mechanism. It links a directory,
    but naming it '<name>.md' makes pathlib's glob("*.md") pick it up exactly
    like a file entry would — which is all _scan()'s per-file gate cares about.
    """
    v = _vault(tmp_path)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "real.txt").write_text("token=super-secret", encoding="utf-8")

    src = tmp_path / "src"
    src.mkdir()
    link = src / "leaked.md"
    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(secrets_dir)],
            check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        pytest.skip(f"无法在本机创建 NTFS junction: {e}")

    with pytest.raises(SecretPathError):
        collect_memory([src], v, "box1", Writer())

def test_collected_memory_round_trips_through_load_vault(tmp_path):
    # Carry-forward defect #1: the old collector wrote to <host>/memory/, a layout
    # memory_dirs()/load_vault() never scans — the memory silently vanished from
    # MEMORY.md. Prove collect-then-read actually round-trips through the real
    # read path, not just that a file landed somewhere on disk.
    from hub.vault import load_vault
    v = _vault(tmp_path)
    src = tmp_path / "src"
    _mem(src, "roundtrip")
    collect_memory([src], v, "box1", Writer())
    vault = load_vault(v)
    assert "roundtrip" in {m.name for m in vault.memories}
