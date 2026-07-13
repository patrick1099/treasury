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
    """金库顶层按归属切:shared/ 共享区(按类型) + <host>/ 备份区(按工具)。"""
    (root / "shared" / "memory").mkdir(parents=True)
    (root / host / "claude" / "memory").mkdir(parents=True)
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / host / "claude" / "memory" / "m1.md").write_text(_mem("m1"), encoding="utf-8")
    (root / host / "device.toml").write_text(
        f'class = ["work"]\nprojects = ["xinao"]\n\n[paths]\nVAULT = "{root.as_posix()}"\n',
        encoding="utf-8")

_RAW_PATH = "装在 C:/Users/me/AppData/Local/Programs 下。"

def test_sync_blocks_raw_path_without_exempt(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "claude" / "memory" / "rp.md").write_text(_mem("rp", body=_RAW_PATH),
                                                   encoding="utf-8")
    rc = main(["sync", "--vault", str(vault), "--host", "h1"])
    assert rc == 1                       # 未豁免 -> 裸路径硬拦
    assert not (vault / "MEMORY.md").exists()

def test_sync_exempts_raw_path_via_list(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "claude" / "memory" / "rp.md").write_text(_mem("rp", body=_RAW_PATH),
                                                   encoding="utf-8")
    (vault / "lint-exempt.txt").write_text("# 豁免\nrp\n", encoding="utf-8")
    rc = main(["sync", "--vault", str(vault), "--host", "h1"])
    assert rc == 0                       # rp 在名单 -> 裸路径放行
    assert (vault / "MEMORY.md").exists()

def test_sync_exempt_does_not_bypass_sensitive(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "claude" / "memory" / "rp.md").write_text(
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
    (vault / "h1" / "claude" / "memory" / "sec.md").write_text(
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
    """给 h1 的 [sources.claude] 段追加 memory 源(collect 目前只读 claude 的源)。"""
    dev_toml = vault / host / "device.toml"
    srcs = ", ".join(f'"{d.as_posix()}"' for d in dirs)
    content = dev_toml.read_text(encoding="utf-8") + f'\n[sources.claude]\nmemory = [{srcs}]\n'
    dev_toml.write_text(content, encoding="utf-8")

def test_collect_lands_in_own_device_folder(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    src = tmp_path / "toolmem"; src.mkdir()
    (src / "new.md").write_text(_mem("newmem"), encoding="utf-8")
    _set_collect_sources(vault, "h1", src)
    rc = main(["collect", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert (vault / "h1" / "claude" / "memory" / "newmem.md").exists()

def test_collect_never_writes_into_shared(tmp_path):
    # 镜像语义：collect 只镜像本机自己那一块，shared/ 碰都不碰——即便金库里
    # 已有同名记忆躺在 shared/，本机 collect 也只写自己的 <host>/claude/memory/，
    # 绝不去改共享区（那是回环污染的老行为，已废弃）。
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    (vault / "shared" / "memory" / "common.md").write_text(_mem("common", body="旧"),
                                                           encoding="utf-8")
    src = tmp_path / "toolmem"; src.mkdir()
    (src / "common.md").write_text(_mem("common", body="新"), encoding="utf-8")
    _set_collect_sources(vault, "h1", src)
    assert main(["collect", "--vault", str(vault), "--host", "h1"]) == 0
    assert "新" in (vault / "h1" / "claude" / "memory" / "common.md").read_text(encoding="utf-8")
    assert "旧" in (vault / "shared" / "memory" / "common.md").read_text(encoding="utf-8")

def test_collect_only_reads_claude_source(tmp_path):
    # device.toml 的源按工具分([sources.claude] / [sources.codex])。collect 目前只读
    # claude 的 memory 源——Codex 没有人写的记忆文件可收(它的记忆是 sqlite 内部流水线，
    # 见 hub/scaffold_vault.py 里的说明)。Task 6 会重写这条命令，届时再展开。
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    claude = tmp_path / "claudemem"; claude.mkdir()
    codex = tmp_path / "codexmem"; codex.mkdir()
    (claude / "a.md").write_text(_mem("from_claude"), encoding="utf-8")
    (codex / "b.md").write_text(_mem("from_codex"), encoding="utf-8")
    dev_toml = vault / "h1" / "device.toml"
    dev_toml.write_text(
        dev_toml.read_text(encoding="utf-8") +
        f'\n[sources.claude]\nmemory = ["{claude.as_posix()}"]\n'
        f'\n[sources.codex]\nmemory = ["{codex.as_posix()}"]\n',
        encoding="utf-8")
    assert main(["collect", "--vault", str(vault), "--host", "h1"]) == 0
    assert (vault / "h1" / "claude" / "memory" / "from_claude.md").exists()
    assert not (vault / "h1" / "claude" / "memory" / "from_codex.md").exists()
