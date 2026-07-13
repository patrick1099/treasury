import subprocess
import pytest
from pathlib import Path
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

def test_missing_source_is_skipped_not_an_error(tmp_path):
    v = _vault(tmp_path)
    r = collect_memory([tmp_path / "nope"], v, "box1", Writer())
    assert r.written == []                    # 工具没装 = 正常，不是错误

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
