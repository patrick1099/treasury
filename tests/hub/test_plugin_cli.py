import json
import pytest
import hub.plugin_cli as plugin_cli
from hub.plugin_cli import (CliCommand, CliResult, run_cli, installed_plugins, marketplaces)

CLAUDE_LIST = json.dumps([{"id":"cjt@cjt","version":"0.1.0","scope":"user","enabled":True,
                           "installPath":"x"}])
CLAUDE_MKT = json.dumps([{"name":"cjt","source":"directory","path":"P","installLocation":"P"}])
CODEX_LIST = json.dumps({"installed":[{"pluginId":"cjt@cjt","name":"cjt","marketplaceName":"cjt",
                          "version":"0.2.0","enabled":True,"source":{"source":"local","path":"Q"}}],
                          "available":[]})
CODEX_MKT = json.dumps({"marketplaces":[{"name":"cjt","root":"Q"}]})
def runner(argv):
    key = " ".join(argv)
    return CliResult(0, {"claude plugin list --json": CLAUDE_LIST,
        "claude plugin marketplace list --json": CLAUDE_MKT,
        "codex plugin list --json": CODEX_LIST,
        "codex plugin marketplace list --json": CODEX_MKT}.get(key, "ok"), "")

def test_run_cli_uses_runner():
    assert run_cli(CliCommand("codex",["plugin","add","cjt@cjt"]), runner=runner).returncode == 0
def test_installed_claude():
    i = installed_plugins("claude", runner=runner)["cjt@cjt"]
    assert i.version=="0.1.0" and i.enabled is True and i.marketplace=="cjt"
def test_installed_codex():
    i = installed_plugins("codex", runner=runner)["cjt@cjt"]
    assert i.version=="0.2.0" and i.enabled is True and i.source_path=="Q"
def test_marketplaces_both():
    assert marketplaces("claude", runner=runner)["cjt"]=="P"
    assert marketplaces("codex", runner=runner)["cjt"]=="Q"
def test_missing_executable_becomes_cli_unavailable(monkeypatch):
    from hub.plugin_cli import CliUnavailable
    monkeypatch.setattr(plugin_cli.subprocess,"run",
                        lambda *a,**k: (_ for _ in ()).throw(FileNotFoundError("missing")))
    with pytest.raises(CliUnavailable):
        run_cli(CliCommand("claude",["plugin","--help"]))
