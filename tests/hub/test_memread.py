import pytest
from pathlib import Path
from hub.memread import read_memory, MemoryNotInView

def _setup(vault, host, name, scope, body):
    (vault / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (vault / host).mkdir(parents=True, exist_ok=True)
    (vault / host / "device.toml").write_text(
        "class = []\nprojects = []\n[paths]\nVAULT = \"" + vault.as_posix() + "\"\n",
        encoding="utf-8")
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\n{body}\n", encoding="utf-8")

def test_reads_in_scope_and_expands_symbols(tmp_path):
    _setup(tmp_path, "box", "a", "[global]", "see $VAULT/shared/memory/a.md")
    out = read_memory(tmp_path, "box", "claude", "a")
    assert tmp_path.as_posix() in out                    # 符号根展开成本机绝对路径
    assert "$VAULT" not in out

def test_refuses_out_of_scope(tmp_path):
    _setup(tmp_path, "box", "a", "[tool:codex]", "body")
    with pytest.raises(MemoryNotInView):                  # claude 视图里没有它
        read_memory(tmp_path, "box", "claude", "a")
