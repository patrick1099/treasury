import subprocess
from pathlib import Path
from hub.cli import main
from hub.backend import GitBackend

def _init_git(repo):
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

def _git(repo, *args):
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

def test_process_offline_remote_does_not_crash(tmp_path):
    # 生产场景：金库总是 clone 自 NAS(总有 origin)；离线时 process 绝不能因 push 失败而崩溃
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    subprocess.run(["git", "remote", "add", "origin", str(tmp_path / "nonexistent-remote")],
                   cwd=vault, check=True, capture_output=True, text=True)
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert (vault / "MEMORY.md").exists()

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

def test_sync_success_publishes(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    rc = main(["sync", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert GitBackend(vault).status().strip() == ""

def test_sync_lint_failure_returns_1(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "memory" / "sec.md").write_text(
        "---\nname: sec\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: true\n---\n密\n",
        encoding="utf-8")
    rc = main(["sync", "--vault", str(vault), "--host", "h1"])
    assert rc == 1

def test_sync_conflict_returns_2(tmp_path):
    # 远端与本地 clone 在同一文件(vault.toml)分叉 -> acquire 内 git pull 非 ff 冲突 -> sync 返回 2
    remote = tmp_path / "remote"; _mk_vault(remote, "h1"); _init_git(remote)
    _git(remote, "add", "-A"); _git(remote, "commit", "-qm", "seed")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True,
                   capture_output=True, text=True)
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "t")
    # 远端前进一步
    (remote / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _git(remote, "commit", "-qam", "remote change")
    # clone 本地也改同文件并提交 -> 分叉
    (clone / "vault.toml").write_text("version = 3\n", encoding="utf-8")
    _git(clone, "commit", "-qam", "local change")
    rc = main(["sync", "--vault", str(clone), "--host", "h1"])
    assert rc == 2

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
