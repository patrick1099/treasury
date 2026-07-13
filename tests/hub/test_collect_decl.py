import json
import subprocess
import tomllib
from pathlib import Path
from hub.collect.decl import collect_claude_decl, collect_codex_decl
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
    r = collect_claude_decl(None, None, tmp_path / "v", Writer())
    assert r.repos == [] and r.enabled == {}

def test_dry_run_writes_nothing(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    collect_claude_decl(devdir, settings, dest, Writer(dry_run=True))
    assert not dest.exists()
