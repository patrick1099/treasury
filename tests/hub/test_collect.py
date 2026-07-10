from pathlib import Path
from hub.collect import collect_memories

def _write(p: Path, name, sensitive=False):
    p.write_text(
        f"---\nname: {name}\ndescription: d\nmetadata:\n  type: project\n"
        f"  scope: [global]\n  portable: true\n  sensitive: {str(sensitive).lower()}\n---\n正文\n",
        encoding="utf-8")

def test_collect_skips_sensitive_and_derived(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    vault_mem = tmp_path / "vault" / "memory"; vault_mem.mkdir(parents=True)
    _write(src / "keep.md", "keep")
    _write(src / "secret.md", "secret", sensitive=True)
    (src / "MEMORY.md").write_text("- 派生物\n", encoding="utf-8")
    (src / "memory-index.md").write_text("派生\n", encoding="utf-8")
    collected = collect_memories([src], vault_mem)
    assert collected == ["keep"]
    assert (vault_mem / "keep.md").exists()
    assert not (vault_mem / "secret.md").exists()

def test_collect_hardening(tmp_path):
    """Test derived-file name gate, UTF-8 decode error handling, and LF line endings."""
    src = tmp_path / "src"; src.mkdir()
    vault_mem = tmp_path / "vault" / "memory"; vault_mem.mkdir(parents=True)

    # (a) MEMORY.md with valid frontmatter is excluded from result and not written
    _write(src / "MEMORY.md", "shouldnotmatter")
    _write(src / "good.md", "good")
    collected = collect_memories([src], vault_mem)
    assert "shouldnotmatter" not in collected
    assert not (vault_mem / "shouldnotmatter.md").exists()
    assert (vault_mem / "good.md").exists()

    # (b) Non-UTF-8 file is skipped gracefully without raising
    src.joinpath("broken.md").write_bytes(
        b"---\nname: broken\ndescription: d\nmetadata:\n  type: project\n"
        b"  scope: [global]\n  portable: true\n  sensitive: false\n---\n\xd5\xd5\n"
    )
    _write(src / "good2.md", "good2")
    collected2 = collect_memories([src], vault_mem)
    assert "broken" not in collected2
    assert "good2" in collected2
    assert (vault_mem / "good2.md").exists()

    # (c) Collected file has LF endings, not CRLF
    data = (vault_mem / "good.md").read_bytes()
    assert b"\r\n" not in data
    data2 = (vault_mem / "good2.md").read_bytes()
    assert b"\r\n" not in data2
