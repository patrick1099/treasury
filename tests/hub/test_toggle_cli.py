import json
import pytest
from pathlib import Path

from hub.cli import main


def _mk_vault(tmp_path, host="box1"):
    vault = tmp_path / "vault"
    (vault / host).mkdir(parents=True)
    (vault / "vault.toml").write_text("""version = 3
""", encoding="utf-8")
    d = vault / "shared" / "skills" / "alpha"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("""# alpha
""", encoding="utf-8")
    homes = tmp_path / "home"
    (vault / host / "device.toml").write_text(
        """class=["work"]
projects=[]
[paths]
CLAUDE_HOME="%s/.claude"
AGENTS_HOME="%s/.agents"
OPENCODE_CONFIG="%s/.config/opencode/opencode.json"
DSH_HOME="%s/.dsh"
DSH_PROFILE="headless"
""" % (homes.as_posix(), homes.as_posix(), homes.as_posix(), homes.as_posix()), encoding="utf-8")
    hub = tmp_path / "hub"
    src = hub / "dsh-claude-plugin-loader" / "dsh-claude-plugin-loader.mjs"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("""export const name = 'dsh-claude-plugin-loader'
""", encoding="utf-8")
    hm = hub / "hub" / "skills" / "hub-memory"
    hm.mkdir(parents=True, exist_ok=True)
    (hm / "SKILL.md").write_text("""# hub-memory
""", encoding="utf-8")
    return vault, hub


def test_toggle_skill_opencode_cli_json_envelope(tmp_path, capsys):
    vault, hub = _mk_vault(tmp_path)
    rc = main(["toggle", "skill", "alpha", "opencode", "on",
               "--vault", str(vault), "--host", "box1", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    envelope = json.loads(out)
    assert envelope["ok"] is True
    assert envelope["error"] is None
    assert envelope["data"]["asset_type"] == "skill"
    assert envelope["data"]["name"] == "alpha"
    assert envelope["data"]["harness"] == "opencode"
    assert envelope["data"]["results"][0]["status"] == "applied"
    assert isinstance(envelope["meta"]["warnings"], list)


def test_toggle_memory_returns_validation(tmp_path, capsys):
    vault, _hub = _mk_vault(tmp_path)
    rc = main(["toggle", "memory", "m1", "claude", "off",
               "--vault", str(vault), "--host", "box1", "--json"])
    err = capsys.readouterr().err
    assert rc == 1
    envelope = json.loads(err)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_VALIDATION"
    assert "只读" in envelope["error"]["message"]


def test_toggle_invalid_harness_with_json_returns_2(tmp_path, capsys):
    vault, _hub = _mk_vault(tmp_path)
    with pytest.raises(SystemExit) as e:
        main(["toggle", "skill", "alpha", "bogus", "on",
              "--vault", str(vault), "--host", "box1", "--json"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    envelope = json.loads(err)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_VALIDATION"


def test_toggle_missing_vault_returns_1(tmp_path, capsys):
    rc = main(["toggle", "skill", "alpha", "opencode", "on", "--json"])
    err = capsys.readouterr().err
    assert rc == 1
    envelope = json.loads(err)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_NOT_FOUND"
