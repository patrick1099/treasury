import subprocess
from pathlib import Path
from hub.cli import main

def _init_git(repo):
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

def _mk_vault(root: Path, host: str):
    (root / "rules").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "devices").mkdir()
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / "rules" / "a.md").write_text("规则A\n", encoding="utf-8")
    (root / "memory" / "m1.md").write_text(
        "---\nname: m1\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n",
        encoding="utf-8")
    tgt = root / "proj"; tgt.mkdir()
    (root / "devices" / f"{host}.toml").write_text(
        f'class = ["work"]\nprojects = ["xinao"]\n\n[paths]\nVAULT = "{root.as_posix()}"\n\n'
        f'[[targets]]\nproject = "xinao"\nroot = "{tgt.as_posix()}"\n',
        encoding="utf-8")
    return tgt

def test_process_regenerates_index_and_commits(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert (vault / "MEMORY.md").exists()
    assert "m1" in (vault / "MEMORY.md").read_text(encoding="utf-8")

def test_pull_materializes_agents_md(tmp_path):
    vault = tmp_path / "vault"; tgt = _mk_vault(vault, "h1"); _init_git(vault)
    rc = main(["pull", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    agents = (tgt / "AGENTS.md").read_text(encoding="utf-8")
    assert "规则A" in agents

def test_process_blocks_sensitive(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "memory" / "sec.md").write_text(
        "---\nname: sec\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: true\n---\n密\n",
        encoding="utf-8")
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 1                       # 敏感记忆混入 -> lint 拦停，不生成索引
    assert not (vault / "MEMORY.md").exists()

def test_collect_pulls_into_vault(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    src = tmp_path / "toolmem"; src.mkdir()
    (src / "new.md").write_text(
        "---\nname: newmem\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n",
        encoding="utf-8")
    dev_toml = vault / "devices" / "h1.toml"
    # NOTE: must insert before the first table header ([paths]/[[targets]]) —
    # TOML nests any bare key appended *after* a table header into that table,
    # not the document root, so a naive append would land inside [[targets]].
    content = dev_toml.read_text(encoding="utf-8").replace(
        "\n[paths]", f'\ncollect_sources = ["{src.as_posix()}"]\n\n[paths]', 1)
    dev_toml.write_text(content, encoding="utf-8")
    rc = main(["collect", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert (vault / "memory" / "newmem.md").exists()
