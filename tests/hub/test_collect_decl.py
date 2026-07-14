import json
import subprocess
import tomllib
from pathlib import Path
import pytest
from hub.collect.decl import collect_claude_decl, collect_codex_decl
from hub.collect.errors import MissingSourceError
from hub.guard import SecretPathError
from hub.writer import Writer

def _mk_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    (repo / "plugin.md").write_text("# " + name, encoding="utf-8")
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "i"]):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/x/{name}.git"],
                   cwd=repo, check=True, capture_output=True)
    return repo

_SETTINGS = {
    "enabledPlugins": {"superpowers@claude-plugins-official": True,
                       "cjt@cjt": True,
                       "compact-plus@xu-local": False},
    "extraKnownMarketplaces": {
        "xu-local": {"source": {"source": "directory", "path": "C:\\x\\plugins-dev"}}},
}

def test_own_plugins_are_snapshotted(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    _mk_repo(devdir, "true-north")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    r = collect_claude_decl(devdir, settings, dest, Writer())
    assert {m.name for m in r.repos} == {"cjt", "true-north"}
    assert (dest / "plugins" / "cjt" / "plugin.md").exists()
    assert not (dest / "plugins" / "cjt" / ".git").exists()

def test_manifest_records_remote_sha_and_enabled(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    collect_claude_decl(devdir, settings, dest, Writer())
    man = tomllib.loads((dest / "plugins.toml").read_text(encoding="utf-8"))
    assert man["repos"]["cjt"]["remote"] == "https://github.com/x/cjt.git"
    assert len(man["repos"]["cjt"]["sha"]) == 40
    assert man["enabled"]["superpowers@claude-plugins-official"] is True
    assert man["enabled"]["compact-plus@xu-local"] is False    # 禁用状态也要记
    assert man["marketplaces"]["xu-local"] == "directory:C:\\x\\plugins-dev"

def test_dirty_repo_is_reported(tmp_path):
    devdir = tmp_path / "plugins-dev"
    repo = _mk_repo(devdir, "cjt")
    (repo / "plugin.md").write_text("改了没提交", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    r = collect_claude_decl(devdir, settings, tmp_path / "v", Writer())
    assert r.dirty == ["cjt"]      # 快照里没有未提交的改动 —— 必须警告

def test_non_repo_dirs_under_plugins_dev_are_skipped(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    (devdir / "docs").mkdir()                       # 没有 .git，不是插件仓
    (devdir / "docs" / "note.md").write_text("笔记", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    r = collect_claude_decl(devdir, settings, tmp_path / "v", Writer())
    assert {m.name for m in r.repos} == {"cjt"}

_CODEX_CFG = """
[plugins."gmail@openai-curated"]
enabled = true

[plugins."superpowers@superpowers-dev"]
enabled = true

[marketplaces.superpowers-dev]
source_type = "git"
source = "https://github.com/obra/superpowers.git"
last_revision = "d884ae0"
"""

def test_codex_decl_copies_declarations_only(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(_CODEX_CFG, encoding="utf-8")
    dest = tmp_path / "vault" / "codex"
    r = collect_codex_decl(cfg, dest, Writer())
    man = tomllib.loads((dest / "plugins.toml").read_text(encoding="utf-8"))
    assert man["enabled"]["gmail@openai-curated"] is True
    assert man["marketplaces"]["superpowers-dev"] == "git:https://github.com/obra/superpowers.git"
    assert r.repos == []            # Codex 本机没有"自己写的"插件 —— 结果如此，不是双标

def test_missing_settings_is_not_an_error(tmp_path):
    """没配(None)= 本机没那个源 = 正常。"""
    r = collect_claude_decl(None, None, tmp_path / "v", Writer())
    assert r.repos == [] and r.enabled == {}

def test_configured_but_missing_settings_refuses(tmp_path):
    """配了、但文件不在 → 配置错误。静默跳过的后果:plugins.toml 里 [enabled] 是空的,
    而 SCHEMA §9 告诉加载器"还原自有插件以 plugins.toml 为准"——它会以为用户没装任何插件。
    """
    with pytest.raises(MissingSourceError, match="nope.json"):
        collect_claude_decl(None, tmp_path / "nope.json", tmp_path / "v", Writer())

def test_configured_but_missing_plugin_repos_refuses(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    with pytest.raises(MissingSourceError, match="no-such-dir"):
        collect_claude_decl(tmp_path / "no-such-dir", settings, tmp_path / "v", Writer())

def test_configured_but_missing_codex_config_refuses(tmp_path):
    with pytest.raises(MissingSourceError, match="nope.toml"):
        collect_codex_decl(tmp_path / "nope.toml", tmp_path / "v", Writer())

# ---- 最终评审 finding 2:一个用户级 hook 曾经让 collect 永久性地半途暴毙 ----

# Claude 的 settings.json 里 hooks 的真实形状:dict of lists of dicts。
_HOOKS = {
    "PreCompact": [
        {"matcher": "*", "hooks": [{"type": "command", "command": "py -3 x.py"}]},
    ],
}

def test_hooks_degrade_instead_of_killing_the_whole_manifest(tmp_path):
    """一个用户级 hook 曾经让 `hub collect` **抛错**,而清单是最后写的 ——
    金库停在"记忆/skill/插件快照都落了、plugins.toml 和 MEMORY.md 没落"的半成品上,
    而且**之后每一次 collect 都同样炸**,备份从此冻结。

    dump_toml 对没见过的形状抛错是**对的**(宁可响不可错,SCHEMA §8),问题是**炸的范围**:
    一个备份区的 TOML 写出器缺一张表,不该把整份备份带走。
    [hooks] 这一张表跳过 + 大声警告,清单的其余部分照写。
    """
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({**_SETTINGS, "hooks": _HOOKS}), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"

    r = collect_claude_decl(None, settings, dest, Writer())     # 不许抛

    man = tomllib.loads((dest / "plugins.toml").read_text(encoding="utf-8"))
    assert "hooks" not in man                                   # 那张表跳过了
    assert man["enabled"]["superpowers@claude-plugins-official"] is True   # 清单其余部分照写
    assert man["marketplaces"]["xu-local"] == "directory:C:\\x\\plugins-dev"
    assert r.hooks == _HOOKS                                    # 报告里仍然如实带着

def test_skipped_hooks_are_reported_loudly(tmp_path, capsys):
    """静默跳过 = 用户以为 hook 备份了,其实没有。必须点名跳了什么、为什么。"""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({**_SETTINGS, "hooks": _HOOKS}), encoding="utf-8")
    collect_claude_decl(None, settings, tmp_path / "v" / "claude", Writer())
    out = capsys.readouterr().out
    assert "hooks" in out and "PreCompact" in out       # 跳了哪张表、里面是什么

def test_scalar_hooks_still_get_written(tmp_path):
    """降级只针对写不出来的形状。真能写的 hooks(纯标量)必须照常进清单——
    别把"跳过 hooks"做成无条件的。"""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({**_SETTINGS, "hooks": {"onStop": "py -3 x.py"}}),
                        encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    collect_claude_decl(None, settings, dest, Writer())
    man = tomllib.loads((dest / "plugins.toml").read_text(encoding="utf-8"))
    assert man["hooks"]["onStop"] == "py -3 x.py"

def test_bad_value_outside_hooks_still_raises(tmp_path):
    """降级**只**给 hooks 开口子。别的键出现没见过的形状,照旧抛错——
    dump_toml 那道"宁可响不可错"不能被这次修改顺手拆掉。"""
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"enabledPlugins": {"x@m": {"nested": "不该出现的形状"}}}),
        encoding="utf-8")
    with pytest.raises(ValueError, match="x@m"):
        collect_claude_decl(None, settings, tmp_path / "v", Writer())

def test_dry_run_writes_nothing(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    collect_claude_decl(devdir, settings, dest, Writer(dry_run=True))
    assert not dest.exists()

def test_plugin_repo_literally_named_secrets_is_rejected(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")              # 字母序排在 secrets 前面，先被处理 —— 正常仓的对照组
    _mk_repo(devdir, "secrets")          # 硬闸目标：目录名字面命中黑名单
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    with pytest.raises(SecretPathError):
        collect_claude_decl(devdir, settings, dest, Writer())
    assert (dest / "plugins" / "cjt" / "plugin.md").exists()      # 正的一半：正常仓仍照常落地
    assert not (dest / "plugins" / "secrets").exists()            # 硬闸拦住，没有进金库

def test_plugin_repo_via_junction_into_secrets_is_rejected(tmp_path):
    devdir = tmp_path / "plugins-dev"
    secrets_root = tmp_path / "secrets"
    secrets_root.mkdir()
    real_repo = _mk_repo(secrets_root, "myplugin")   # 真身是 secrets/ 下的一个 git 仓
    devdir.mkdir(parents=True, exist_ok=True)
    link = devdir / "myplugin"                       # 名字本身无辜
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real_repo)],
                            capture_output=True)
    if result.returncode != 0:
        pytest.skip(f"无法创建 NTFS junction，跳过（可能非 Windows 或权限不足）: {result.stderr!r}")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    with pytest.raises(SecretPathError):
        collect_claude_decl(devdir, settings, dest, Writer())
    assert not (dest / "plugins" / "myplugin").exists()
