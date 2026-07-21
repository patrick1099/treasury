import json
import pytest
from pathlib import Path
from hub.plugin_manifest import (load_plugin_manifest, check_identity, plugin_version,
                                 PluginIdentityError, PluginManifestError)

def _plugin(vault, name, mkt=None, plug=None, ver="0.1.0"):
    d = vault/"shared/plugins"/name/".claude-plugin"; d.mkdir(parents=True)
    (d/"marketplace.json").write_text(json.dumps(
        {"name": mkt or name, "plugins":[{"name": plug or name, "source":".","description":"d"}]}),
        encoding="utf-8")
    (d/"plugin.json").write_text(json.dumps({"name": plug or name, "version": ver}), encoding="utf-8")

def _manifest(vault, body):
    (vault/"shared/plugins").mkdir(parents=True, exist_ok=True)
    (vault/"shared/plugins/manifest.toml").write_text(body, encoding="utf-8")

def test_load_version_identity_ok(tmp_path):
    _manifest(tmp_path, '[cjt]\nplatforms = ["claude","codex"]\n')
    _plugin(tmp_path, "cjt")
    e = load_plugin_manifest(tmp_path)[0]
    assert e.name=="cjt" and e.platforms==["claude","codex"] and e.remote is None
    check_identity(tmp_path, e)
    assert plugin_version(tmp_path, "cjt") == "0.1.0"

def test_platforms_required(tmp_path):
    _manifest(tmp_path, '[cjt]\n')      # 缺 platforms
    _plugin(tmp_path, "cjt")
    with pytest.raises(PluginManifestError):
        load_plugin_manifest(tmp_path)

def test_identity_mismatch(tmp_path):
    _manifest(tmp_path, '[cjt]\nplatforms = ["claude"]\n')
    _plugin(tmp_path, "cjt", plug="WRONG")
    with pytest.raises(PluginIdentityError):
        check_identity(tmp_path, load_plugin_manifest(tmp_path)[0])

def test_remote_optional_repo(tmp_path):
    _manifest(tmp_path, '[cjt]\nplatforms=["claude"]\n[cjt.repository]\nremote="git@x"\n')
    _plugin(tmp_path, "cjt")
    assert load_plugin_manifest(tmp_path)[0].remote == "git@x"

def test_identity_rejects_case_mismatched_dir(tmp_path):
    # manifest key is "cjt" but the actual on-disk directory is "CJT" (Windows/macOS
    # case-insensitive filesystems would otherwise silently accept this). The JSON
    # contents inside are correctly named "cjt", so only the directory-name check
    # (previously a tautological no-op comparing n to n) can catch this.
    _manifest(tmp_path, '[cjt]\nplatforms = ["claude"]\n')
    _plugin(tmp_path, "CJT", mkt="cjt", plug="cjt")
    with pytest.raises(PluginIdentityError):
        check_identity(tmp_path, load_plugin_manifest(tmp_path)[0])

def test_identity_missing_claude_plugin_dir(tmp_path):
    # The plugin's top-level directory exists on disk (so the casefold lookup
    # succeeds) but it has no .claude-plugin/ subdirectory at all.
    _manifest(tmp_path, '[cjt]\nplatforms = ["claude"]\n')
    (tmp_path/"shared/plugins/cjt").mkdir(parents=True)
    with pytest.raises(PluginIdentityError):
        check_identity(tmp_path, load_plugin_manifest(tmp_path)[0])
