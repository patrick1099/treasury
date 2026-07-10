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
