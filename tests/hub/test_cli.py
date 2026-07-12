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

def _mem(name: str, sensitive: str = "false", body: str = "正文") -> str:
    return (f"---\nname: {name}\ndescription: d\nmetadata:\n  type: project\n"
            f"  scope: [global]\n  portable: true\n  sensitive: {sensitive}\n---\n{body}\n")

def _mk_vault(root: Path, host: str):
    """金库顶层按归属切:shared/ 公共池 + <host>/ 本机家当。"""
    (root / "shared" / "rules").mkdir(parents=True)
    (root / "shared" / "memory").mkdir()
    (root / host / "memory").mkdir(parents=True)
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / "shared" / "rules" / "a.md").write_text("规则A\n", encoding="utf-8")
    (root / host / "memory" / "m1.md").write_text(_mem("m1"), encoding="utf-8")
    tgt = root / "proj"; tgt.mkdir()
    (root / host / "device.toml").write_text(
        f'class = ["work"]\nprojects = ["xinao"]\n\n[paths]\nVAULT = "{root.as_posix()}"\n\n'
        f'[[targets]]\nproject = "xinao"\nroot = "{tgt.as_posix()}"\n',
        encoding="utf-8")
    return tgt

_RAW_PATH = "装在 C:/Users/me/AppData/Local/Programs 下。"

def test_sync_exempt_does_not_bypass_sensitive(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "memory" / "rp.md").write_text(
        _mem("rp", sensitive="true", body=_RAW_PATH), encoding="utf-8")
    (vault / "lint-exempt.txt").write_text("rp\n", encoding="utf-8")
    rc = main(["sync", "--vault", str(vault), "--host", "h1"])
    assert rc == 1                       # 豁免只放行裸路径，sensitive 仍硬拦
    assert not (vault / "MEMORY.md").exists()

def test_sync_success_publishes(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    rc = main(["sync", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert GitBackend(vault).status().strip() == ""

def test_sync_lint_failure_returns_1(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "memory" / "sec.md").write_text(
        _mem("sec", sensitive="true", body="密"), encoding="utf-8")
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

def _set_collect_sources(vault: Path, host: str, *dirs: Path) -> None:
    dev_toml = vault / host / "device.toml"
    # NOTE: must insert before the first table header ([paths]/[[targets]]) —
    # TOML nests any bare key appended *after* a table header into that table,
    # not the document root, so a naive append would land inside [[targets]].
    srcs = ", ".join(f'"{d.as_posix()}"' for d in dirs)
    content = dev_toml.read_text(encoding="utf-8").replace(
        "\n[paths]", f'\ncollect_sources = [{srcs}]\n\n[paths]', 1)
    dev_toml.write_text(content, encoding="utf-8")

def test_collect_lands_in_own_device_folder(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    src = tmp_path / "toolmem"; src.mkdir()
    (src / "new.md").write_text(_mem("newmem"), encoding="utf-8")
    _set_collect_sources(vault, "h1", src)
    rc = main(["collect", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert (vault / "h1" / "memory" / "newmem.md").exists()

def test_collect_writes_back_to_original_owner(tmp_path):
    # 公共池的记忆被 pull 到工具目录、又被 collect 收回来时，必须写回 shared/，
    # 不能在本机文件夹里复制出一个孪生体（否则就是回环污染）
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    (vault / "shared" / "memory" / "common.md").write_text(_mem("common", body="旧"),
                                                           encoding="utf-8")
    src = tmp_path / "toolmem"; src.mkdir()
    (src / "common.md").write_text(_mem("common", body="新"), encoding="utf-8")
    _set_collect_sources(vault, "h1", src)
    assert main(["collect", "--vault", str(vault), "--host", "h1"]) == 0
    assert not (vault / "h1" / "memory" / "common.md").exists()   # 没在本机复制孪生体
    assert "新" in (vault / "shared" / "memory" / "common.md").read_text(encoding="utf-8")

def test_collect_scans_both_claude_and_codex(tmp_path):
    # 本机内 Claude 与 Codex 的记忆双向共享：两边的源都要收进金库
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    claude = tmp_path / "claudemem"; claude.mkdir()
    codex = tmp_path / "codexmem"; codex.mkdir()
    (claude / "a.md").write_text(_mem("from_claude"), encoding="utf-8")
    (codex / "b.md").write_text(_mem("from_codex"), encoding="utf-8")
    _set_collect_sources(vault, "h1", claude, codex)
    assert main(["collect", "--vault", str(vault), "--host", "h1"]) == 0
    assert (vault / "h1" / "memory" / "from_claude.md").exists()
    assert (vault / "h1" / "memory" / "from_codex.md").exists()
