import io
import json
import subprocess
import sys
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
    # m1(_mk_vault 预置)在新源里已经没有了 -> 会触发删除确认，用 --yes 跳过交互
    rc = main(["collect", "--vault", str(vault), "--host", "h1", "--yes"])
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
    assert main(["collect", "--vault", str(vault), "--host", "h1", "--yes"]) == 0
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
    assert main(["collect", "--vault", str(vault), "--host", "h1", "--yes"]) == 0
    assert (vault / "h1" / "claude" / "memory" / "from_claude.md").exists()
    assert not (vault / "h1" / "claude" / "memory" / "from_codex.md").exists()


# ---- Task 11: collect 汇总四条流水线 + bootstrap ----
# 下面这组测试用独立命名的 _mk_backup_vault(而不是复用上面 sync/旧 collect 用的
# _mk_vault),避免签名冲突(上面的 _mk_vault(root, host) 直接写进传入的 root；
# 这里的版本自己在 tmp_path 下开 vault/ 子目录、顺带 git init，两者语义不同，
# 硬改名共用只会让两组测试互相踩)。

def _mk_backup_vault(tmp_path: Path, host: str = "box1") -> Path:
    v = tmp_path / "vault"
    (v / host / "claude" / "memory").mkdir(parents=True)
    (v / "shared" / "memory").mkdir(parents=True)
    (v / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=v, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=v, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=v, check=True)
    return v

def _mk_sources(tmp_path: Path) -> dict:
    mem = tmp_path / "cl" / "projects" / "p" / "memory"
    mem.mkdir(parents=True)
    (mem / "a.md").write_text(
        "---\nname: a\ndescription: a 摘要\nmetadata:\n  type: reference\n"
        "  scope: [global]\n---\n正文\n", encoding="utf-8")
    sk = tmp_path / "cl" / "skills" / "alpha"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
    st = tmp_path / "cl" / "settings.json"
    st.write_text(json.dumps({"enabledPlugins": {"x@m": True}}), encoding="utf-8")
    return {"memory": [mem.as_posix()], "skills": (tmp_path / "cl" / "skills").as_posix(),
            "settings": st.as_posix()}

def _write_device(v: Path, host: str, s: dict):
    (v / host / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n'
        f'CLAUDE_HOME = "{(v.parent / "cl").as_posix()}"\n\n'
        "[sources.claude]\n"
        f'memory = ["{s["memory"][0]}"]\n'
        f'skills = "{s["skills"]}"\n'
        f'settings = "{s["settings"]}"\n',
        encoding="utf-8")

def test_collect_fills_backup_zone(tmp_path):
    v = _mk_backup_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    assert main(["collect", "--vault", str(v), "--host", "box1", "--yes"]) == 0
    assert (v / "box1" / "claude" / "memory" / "a.md").exists()
    assert (v / "box1" / "claude" / "skills" / "alpha" / "SKILL.md").exists()
    assert (v / "box1" / "claude" / "plugins.toml").exists()

def test_collect_dry_run_writes_nothing(tmp_path):
    v = _mk_backup_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    assert main(["collect", "--vault", str(v), "--host", "box1", "--dry-run"]) == 0
    assert not (v / "box1" / "claude" / "memory" / "a.md").exists()
    assert not (v / "box1" / "claude" / "skills").exists()

def test_collect_dry_run_preserves_existing_content(tmp_path):
    # 空目录/不存在这类断言容易写成 vacuous test(没建过目标就断言它不存在)。
    # 这里先在目标位置放真内容，--dry-run 后逐字节校验它原封不动。
    v = _mk_backup_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    existing = v / "box1" / "claude" / "memory" / "old.md"
    existing.write_text(
        "---\nname: old\ndescription: d\nmetadata:\n  type: reference\n"
        "  scope: [global]\n---\n旧内容\n", encoding="utf-8")
    before = existing.read_bytes()
    assert main(["collect", "--vault", str(v), "--host", "box1", "--dry-run"]) == 0
    assert existing.read_bytes() == before

def test_collect_never_touches_shared(tmp_path):
    v = _mk_backup_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    pooled = v / "shared" / "memory" / "p.md"
    pooled.write_text("---\nname: p\ndescription: d\n---\n公共\n", encoding="utf-8")
    before = pooled.read_bytes()
    main(["collect", "--vault", str(v), "--host", "box1", "--yes"])
    assert pooled.read_bytes() == before

def test_collect_regenerates_index(tmp_path):
    v = _mk_backup_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    main(["collect", "--vault", str(v), "--host", "box1", "--yes"])
    idx = (v / "MEMORY.md").read_text(encoding="utf-8")
    assert "[a](box1/claude/memory/a.md)" in idx

def test_collect_without_yes_aborts_when_it_would_delete(tmp_path, monkeypatch, capsys):
    v = _mk_backup_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    stale = v / "box1" / "claude" / "memory" / "gone.md"
    stale.write_text("---\nname: gone\ndescription: d\n---\n旧\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert main(["collect", "--vault", str(v), "--host", "box1"]) == 1
    assert stale.exists()                         # 没确认就不删
    assert "gone" in capsys.readouterr().out      # 但要把要删的列出来


def test_bootstrap_installs_loader_skill_into_tool_home(tmp_path):
    v = _mk_backup_vault(tmp_path)
    loader = v / "shared" / "skills" / "hub-loader"
    loader.mkdir(parents=True)
    (loader / "SKILL.md").write_text("# loader\n", encoding="utf-8")
    claude_home = tmp_path / "cl"
    (v / "box1" / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n'
        f'CLAUDE_HOME = "{claude_home.as_posix()}"\n',
        encoding="utf-8")
    assert main(["bootstrap", "--vault", str(v), "--host", "box1"]) == 0
    assert (claude_home / "skills" / "hub-loader" / "SKILL.md").exists()

def test_bootstrap_dry_run_preserves_existing_content(tmp_path):
    v = _mk_backup_vault(tmp_path)
    loader = v / "shared" / "skills" / "hub-loader"
    loader.mkdir(parents=True)
    (loader / "SKILL.md").write_text("# 新版\n", encoding="utf-8")
    claude_home = tmp_path / "cl"
    dest = claude_home / "skills" / "hub-loader"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("# 旧版真实内容\n", encoding="utf-8")
    before = (dest / "SKILL.md").read_bytes()
    (v / "box1" / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n'
        f'CLAUDE_HOME = "{claude_home.as_posix()}"\n',
        encoding="utf-8")
    assert main(["bootstrap", "--vault", str(v), "--host", "box1", "--dry-run"]) == 0
    assert (dest / "SKILL.md").read_bytes() == before

def test_bootstrap_without_loader_skills_returns_1(tmp_path):
    v = _mk_backup_vault(tmp_path)
    (v / "box1" / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n'
        f'CLAUDE_HOME = "{(tmp_path / "cl").as_posix()}"\n',
        encoding="utf-8")
    assert main(["bootstrap", "--vault", str(v), "--host", "box1"]) == 1


# ---- Task 11 review: Finding 2 (⚠ on a GBK console) + Finding 3 (dry-run wording) ----

def test_secret_scan_warning_survives_gbk_stdout(tmp_path, monkeypatch):
    """本机 py -3 -c "print(sys.stdout.encoding)" 报 gbk,gbk 编不出 U+26A0(⚠)。
    secrets-scan 命中时 cli.py 直接 print() 含 ⚠ 的警告——一旦命中,唯一该报警的
    时刻反而以 UnicodeEncodeError 崩溃。用一个 encoding=gbk/errors=strict 的
    TextIOWrapper 顶替 sys.stdout 来复现同款失败,不依赖真实控制台编码。"""
    v = _mk_backup_vault(tmp_path)
    src = tmp_path / "toolmem"
    src.mkdir()
    (src / "leak.md").write_text(
        _mem("leak", body="sk-" + "a" * 25), encoding="utf-8")
    (v / "box1" / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n\n'
        f'[sources.claude]\nmemory = ["{src.as_posix()}"]\n',
        encoding="utf-8")

    buf = io.BytesIO()
    fake_stdout = io.TextIOWrapper(buf, encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    try:
        rc = main(["collect", "--vault", str(v), "--host", "box1", "--yes"])
    finally:
        fake_stdout.flush()
    assert rc == 0
    printed = buf.getvalue().decode("gbk")
    assert "疑似密钥" in printed        # 警告真的印出来了，不是被吞掉

def test_collect_validates_vault_before_writing_anything(tmp_path):
    """最终评审 finding 3:_cmd_collect 在 run_all **写完之后**才 load_vault(),而
    load_vault() 会解析金库里的**每一条**记忆(含 shared/ 和别的设备的)。于是:

      项目 C 往 shared/ 提升一条带 `sensitive: false  # 不入库` 的记忆(_require_bool
      正好catch 的形状,而且是 Claude 自己会写出来的形状)
        → 备份写成功了,collect 抛错,MEMORY.md **停在旧版本**
        → SCHEMA §5 明确告诉 C"索引里没有的记忆,金库里就是没有,不必自己遍历兜底"
        → 那条记忆在 C 眼里**人间蒸发**,而它明明躺在金库里
        → 而且 collect 和 sync 从此都是死的,直到有人手工去改金库。

    先验后写:坏记忆必须在**动笔之前**就把这次 run 拦下来,金库一个字节都不变,
    索引也就永远不会陈旧。
    """
    v = _mk_backup_vault(tmp_path)
    (v / "box1" / "claude" / "memory" / "m1.md").write_text(_mem("m1"), encoding="utf-8")
    idx = v / "MEMORY.md"
    idx.write_text("# 旧索引\n", encoding="utf-8")
    idx_before = idx.read_bytes()

    # C 提升进 shared/ 的一条坏记忆(行内注释 → sensitive 不是真布尔 → FrontmatterError)
    (v / "shared" / "memory" / "promoted.md").write_text(
        "---\nname: promoted\ndescription: d\nmetadata:\n  type: reference\n"
        "  scope: [global]\n  sensitive: false  # 不入库\n---\n正文\n", encoding="utf-8")

    src = tmp_path / "toolmem"
    src.mkdir()
    (src / "new.md").write_text(_mem("newmem"), encoding="utf-8")
    (v / "box1" / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n\n'
        f'[sources.claude]\nmemory = ["{src.as_posix()}"]\n',
        encoding="utf-8")

    rc = main(["collect", "--vault", str(v), "--host", "box1", "--yes"])

    assert rc != 0
    # 什么都没写:备份没落盘,索引没变 —— 不存在"备份成功了但索引陈旧"的中间态
    assert not (v / "box1" / "claude" / "memory" / "newmem.md").exists()
    assert idx.read_bytes() == idx_before

def test_collect_with_missing_configured_source_refuses_instead_of_wiping_vault(tmp_path):
    """最终评审 finding 1(CRITICAL)的端到端复现:device.toml 里配着一个**不存在**的
    记忆源(scaffold --force 写回的 <占位> 模板正是这个形状),`collect --yes` 曾经把
    金库里的记忆**全部删光**,还返回 0。金库是这些记忆的唯一备份。

    现在:拒绝执行,点名那个路径,一条记忆都不许删。
    """
    v = _mk_backup_vault(tmp_path)
    home = v / "box1" / "claude" / "memory"
    for n in ("m1", "m2", "m3"):
        (home / f"{n}.md").write_text(_mem(n), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in home.glob("*.md")}

    missing = tmp_path / "gone" / "memory"          # 配了,但根本不存在
    (v / "box1" / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n\n'
        f'[sources.claude]\nmemory = ["{missing.as_posix()}"]\n',
        encoding="utf-8")

    rc = main(["collect", "--vault", str(v), "--host", "box1", "--yes"])

    assert rc != 0                                                   # 不能报成功
    assert {p.name: p.read_bytes() for p in home.glob("*.md")} == before   # 一个字节都没动

def test_bootstrap_dry_run_message_is_not_past_tense(tmp_path):
    """Finding 3: --dry-run 下什么都没装，措辞不能用"已装"这种既成事实的过去式。"""
    v = _mk_backup_vault(tmp_path)
    loader = v / "shared" / "skills" / "hub-loader"
    loader.mkdir(parents=True)
    (loader / "SKILL.md").write_text("# loader\n", encoding="utf-8")
    claude_home = tmp_path / "cl"
    (v / "box1" / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n'
        f'CLAUDE_HOME = "{claude_home.as_posix()}"\n',
        encoding="utf-8")
    import io as _io
    import contextlib
    out = _io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = main(["bootstrap", "--vault", str(v), "--host", "box1", "--dry-run"])
    assert rc == 0
    assert not (claude_home / "skills" / "hub-loader").exists()   # 真没装
    assert "已装" not in out.getvalue()


# ---- Task 6: register/promote CLI 接线 + status 并入 link_status ----

def _mini_vault(tmp_path):
    from hub.scaffold_vault import scaffold
    from hub.writer import Writer as _W
    scaffold(tmp_path, "box1", _W())
    dev = tmp_path / "box1" / "device.toml"
    dev.write_text(
        f'class=["work"]\nprojects=[]\n[paths]\n'
        f'CLAUDE_HOME="{(tmp_path / "h" / ".claude").as_posix()}"\n'
        f'AGENTS_HOME="{(tmp_path / "h" / ".agents").as_posix()}"\n',
        encoding="utf-8")
    return tmp_path

def test_cli_register_builds_links(tmp_path, capsys):
    vault = _mini_vault(tmp_path)
    s = vault / "shared" / "skills" / "alpha"; s.mkdir(parents=True)
    (s / "SKILL.md").write_text("# a\n", encoding="utf-8")
    rc = main(["register", "--vault", str(vault), "--host", "box1"])
    assert rc == 0
    assert (tmp_path / "h" / ".claude" / "skills" / "alpha" / "SKILL.md").exists()

def test_cli_promote_conflict_returns_1(tmp_path, capsys):
    vault = _mini_vault(tmp_path)
    existing = vault / "shared" / "skills" / "alpha"; existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("# 共享区版本\n", encoding="utf-8")
    src = vault / "box1" / "claude" / "skills" / "alpha"; src.mkdir(parents=True)
    (src / "SKILL.md").write_text("# 不同版本\n", encoding="utf-8")
    rc = main(["promote", "--vault", str(vault), "--host", "box1",
               "--tool", "claude", "--name", "alpha"])
    assert rc == 1
    assert "alpha" in capsys.readouterr().out

def test_cli_register_conflict_returns_1(tmp_path, capsys):
    # register 的只读预检：目标位置已被"非 hub 管理"的真目录占用(用户自己的东西，
    # 不是我们建的链接)→ RegisterConflict → _cmd_register 的 except 打印+return 1，
    # 一个字节都不许写(既不能顶替这个位置，也不能去建 AGENTS_HOME 那条链)。
    vault = _mini_vault(tmp_path)
    s = vault / "shared" / "skills" / "alpha"; s.mkdir(parents=True)
    (s / "SKILL.md").write_text("# a\n", encoding="utf-8")
    user_dir = tmp_path / "h" / ".claude" / "skills" / "alpha"
    user_dir.mkdir(parents=True)
    (user_dir / "own.txt").write_text("用户自己的东西\n", encoding="utf-8")
    rc = main(["register", "--vault", str(vault), "--host", "box1"])
    assert rc == 1
    assert "alpha" in capsys.readouterr().out
    # 冲突位置原封不动：还是用户的真目录，没被换成 hub 的链接
    assert user_dir.is_dir()
    assert not user_dir.is_symlink()
    assert (user_dir / "own.txt").exists()
    # 预检是"全过才写"：AGENTS_HOME 那条本来没冲突，但因为整体校验没过关，也没建
    assert not (tmp_path / "h" / ".agents" / "skills" / "alpha").exists()

def test_cli_promote_missing_skill_returns_1(tmp_path, capsys):
    # 备份区里根本没有这把 skill -> promote_skill 的 src.is_dir() 检查抛
    # FileNotFoundError -> _cmd_promote 的 except (PromoteConflict, FileNotFoundError,
    # ValueError) 兜住、打印、return 1。
    vault = _mini_vault(tmp_path)
    rc = main(["promote", "--vault", str(vault), "--host", "box1",
               "--tool", "claude", "--name", "does_not_exist"])
    assert rc == 1
    assert "does_not_exist" in capsys.readouterr().out
    assert not (vault / "shared" / "skills" / "does_not_exist").exists()

def test_cli_promote_illegal_name_returns_1(tmp_path, capsys):
    # --name 含路径穿越（"../evil"）-> promote_skill 的 _single_component 校验
    # 命中"/"，抛 ValueError -> 同一个 except 元组兜住、打印、return 1。
    # （argparse 对 --name 没做值校验，是 promote_skill 自己在动笔前把它挡下来的。）
    vault = _mini_vault(tmp_path)
    rc = main(["promote", "--vault", str(vault), "--host", "box1",
               "--tool", "claude", "--name", "../evil"])
    assert rc == 1
    assert "../evil" in capsys.readouterr().out
    assert not (vault / "shared" / "skills" / "evil").exists()

def test_cli_register_without_device_toml_returns_1(tmp_path):
    # 本机没跑过 scaffold(没有 <host>/device.toml)时,register 需要 device.toml
    # 才能算出 skill_targets——load_device 抛 FileNotFoundError,_cmd_register 必须
    # 干净地 return 1(打印清楚的信息),不能让 traceback 冒出来。
    v = _mk_backup_vault(tmp_path)
    rc = main(["register", "--vault", str(v), "--host", "box1"])
    assert rc == 1

def test_cli_promote_without_device_toml_returns_1(tmp_path):
    # 同款缺口:promote 里 load_device 以前在 try 之外,缺 device.toml 时会 traceback。
    v = _mk_backup_vault(tmp_path)
    rc = main(["promote", "--vault", str(v), "--host", "box1",
               "--tool", "claude", "--name", "alpha"])
    assert rc == 1

def test_cli_status_without_device_toml_does_not_crash(tmp_path):
    # 本机没跑过 scaffold(即没有 <host>/device.toml)时,status 只报 git 状态、
    # 不能因为 load_device 抛 FileNotFoundError 而崩溃(旧行为的向后兼容)。
    v = _mk_backup_vault(tmp_path)
    rc = main(["status", "--vault", str(v), "--host", "box1"])
    assert rc == 0

def test_cli_status_appends_link_status(tmp_path, capsys):
    vault = _mini_vault(tmp_path)
    _init_git(vault)
    s = vault / "shared" / "skills" / "alpha"; s.mkdir(parents=True)
    (s / "SKILL.md").write_text("# a\n", encoding="utf-8")
    rc = main(["status", "--vault", str(vault), "--host", "box1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skill 链接:" in out
    assert "missing" in out and "alpha" in out
