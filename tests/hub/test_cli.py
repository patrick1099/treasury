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

def _foreign(root: Path, origin: str, name: str, body: str = "外来正文") -> None:
    """在金库里伪造一台别的设备产的记忆。"""
    d = root / origin / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(_mem(name, body=body), encoding="utf-8")

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

def test_pull_preserves_crlf_in_existing_file(tmp_path):
    # 仓库里的 AGENTS.md 常是 CRLF；pull 若按 LF 写回，git 会记成整文件重写
    vault = tmp_path / "vault"; tgt = _mk_vault(vault, "h1"); _init_git(vault)
    (tgt / "AGENTS.md").write_bytes(b"# \xe5\x8e\x9f\xe6\x96\x87\r\n\r\n\xe6\xad\xa3\xe6\x96\x87\r\n")
    rc = main(["pull", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    raw = (tgt / "AGENTS.md").read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")   # 没有混进裸 LF
    # 新建的 CLAUDE.md 之前不存在 -> 仍用 LF
    assert b"\r\n" not in (tgt / "CLAUDE.md").read_bytes()

def test_process_blocks_sensitive(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "memory" / "sec.md").write_text(
        _mem("sec", sensitive="true", body="密"), encoding="utf-8")
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 1                       # 敏感记忆混入 -> lint 拦停，不生成索引
    assert not (vault / "MEMORY.md").exists()

_RAW_PATH = "装在 C:/Users/me/AppData/Local/Programs 下。"

def test_process_blocks_raw_path_without_exempt(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "memory" / "rp.md").write_text(_mem("rp", body=_RAW_PATH),
                                                   encoding="utf-8")
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 1                       # 未豁免 -> 裸路径硬拦
    assert not (vault / "MEMORY.md").exists()

def test_process_exempts_raw_path_via_list(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "memory" / "rp.md").write_text(_mem("rp", body=_RAW_PATH),
                                                   encoding="utf-8")
    (vault / "lint-exempt.txt").write_text("# 豁免\nrp\n", encoding="utf-8")
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 0                       # rp 在名单 -> 裸路径放行
    assert (vault / "MEMORY.md").exists()

def test_exempt_does_not_bypass_sensitive(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "h1" / "memory" / "rp.md").write_text(
        _mem("rp", sensitive="true", body=_RAW_PATH), encoding="utf-8")
    (vault / "lint-exempt.txt").write_text("rp\n", encoding="utf-8")
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 1                       # 豁免只放行裸路径，sensitive 仍硬拦
    assert not (vault / "MEMORY.md").exists()

def test_pull_dry_run_writes_nothing(tmp_path, capsys):
    # 预览与真实落地共用同一条写路径，闸设在 _write 里——不会出现"预览其实写了真盘"
    vault = tmp_path / "vault"; tgt = _mk_vault(vault, "h1"); _init_git(vault)
    before = b"# \xe5\x8e\x9f\xe6\x96\x87\n"
    (tgt / "AGENTS.md").write_bytes(before)
    assert main(["pull", "--vault", str(vault), "--host", "h1", "--dry-run"]) == 0
    assert (tgt / "AGENTS.md").read_bytes() == before      # 原件一个字节没动
    assert not (tgt / "CLAUDE.md").exists()                # 该新建的也没建
    out = capsys.readouterr().out
    assert "dry-run" in out and "AGENTS.md" in out         # 但报告了要写什么

# ---- 跨设备人工闸门 ----

def test_pull_does_not_materialize_foreign_memory(tmp_path, capsys):
    # 别的设备塞进金库的记忆，未经拍板绝不落地
    vault = tmp_path / "vault"; tgt = _mk_vault(vault, "h1"); _init_git(vault)
    _foreign(vault, "h2", "theirs")
    assert main(["pull", "--vault", str(vault), "--host", "h1"]) == 0
    assert "外来正文" not in (tgt / "AGENTS.md").read_text(encoding="utf-8")
    assert "待审" in capsys.readouterr().out          # 但要提示有待审的

def test_accept_then_pull_materializes(tmp_path):
    vault = tmp_path / "vault"; tgt = _mk_vault(vault, "h1"); _init_git(vault)
    _foreign(vault, "h2", "theirs")
    assert main(["accept", "--vault", str(vault), "--host", "h1", "h2/theirs"]) == 0
    assert "h2/theirs" in (vault / "h1" / "merged.txt").read_text(encoding="utf-8")
    from hub.vault import load_vault
    from hub import roster
    mems = roster.visible(load_vault(vault).memories, "h1",
                          roster.load_merged(vault, "h1"))
    assert {m.name for m in mems} == {"m1", "theirs"}   # 接受后本机可见

def test_reject_removes_from_pending_and_review_all_brings_back(tmp_path, capsys):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    _foreign(vault, "h2", "theirs")
    assert main(["reject", "--vault", str(vault), "--host", "h1", "h2/theirs"]) == 0
    main(["review", "--vault", str(vault), "--host", "h1"])
    assert "没有待审" in capsys.readouterr().out       # 拒过的不再打扰
    main(["review", "--vault", str(vault), "--host", "h1", "--all"])
    assert "h2/theirs" in capsys.readouterr().out     # --all 忽略名单，重新过一遍

def test_review_prints_body_for_ai_to_judge(tmp_path, capsys):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    _foreign(vault, "h2", "theirs", body="他机的独门知识")
    assert main(["review", "--vault", str(vault), "--host", "h1"]) == 0
    out = capsys.readouterr().out
    assert "h2/theirs" in out
    assert "他机的独门知识" in out                     # 正文要打出来，供预读判断

def test_promote_moves_to_shared_pool(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    _foreign(vault, "h2", "theirs")
    assert main(["promote", "--vault", str(vault), "--host", "h1", "h2/theirs"]) == 0
    assert not (vault / "h2" / "memory" / "theirs.md").exists()
    assert (vault / "shared" / "memory" / "theirs.md").exists()
    # 进了公共池 -> 对任何设备都天然可见，不再需要审
    from hub.vault import load_vault
    from hub import roster
    mems = load_vault(vault).memories
    assert "theirs" not in {m.name for m in roster.pending(mems, "h3", set(), set())}
    assert "theirs" in {m.name for m in roster.visible(mems, "h3", set())}

def test_shared_pool_visible_to_every_device(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    (vault / "shared" / "memory" / "common.md").write_text(_mem("common"), encoding="utf-8")
    from hub.vault import load_vault
    from hub import roster
    mems = load_vault(vault).memories
    assert "common" in {m.name for m in roster.visible(mems, "h9", set())}

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
