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

# --- 子进程输出的解码:绝不能落到本机 locale 上 ---
# 真机事故(2026-07-23):`claude plugin --help` 里有个非 ASCII 字符,本机 preferred
# encoding 是 cp936 → 读取线程 UnicodeDecodeError → p.stdout 变成 None(返回码仍是 0)
# → preflight_cli 的 `plug.stdout + mkt.stdout` 抛 TypeError,refresh 整条跑不完。

def test_run_cli_decodes_utf8_not_locale(monkeypatch):
    """不许把解码交给机器 locale——必须显式 utf-8 且不因坏字节丢掉整份输出。"""
    seen = {}
    class _P:
        returncode, stdout, stderr = 0, "", ""
    def fake_run(argv, **kw):
        seen.update(kw)
        return _P()
    monkeypatch.setattr(plugin_cli.subprocess, "run", fake_run)
    run_cli(CliCommand("claude", ["plugin", "--help"]))
    assert (seen.get("encoding") or "").lower().replace("-", "") == "utf8", \
        f"run_cli 必须显式指定 utf-8,实际 kwargs={seen}"
    assert seen.get("errors"), "run_cli 必须指定 errors 容错,否则坏字节会让整份 stdout 变成 None"

def test_run_cli_survives_non_ascii_child_output():
    """端到端:子进程吐 UTF-8 非 ASCII 字节,stdout 必须是字符串而不是 None。"""
    import sys
    r = run_cli(CliCommand(sys.executable,
        ["-c", r"import sys; sys.stdout.buffer.write('—…'.encode('utf-8'))"]))
    assert r.returncode == 0
    assert r.stdout is not None, "坏解码会让 stdout 变成 None,下游 str 运算即崩"
    assert "—" in r.stdout
