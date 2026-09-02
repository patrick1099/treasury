import json
from pathlib import Path
from hub.cli import main
from hub.plugin_cli import CliResult
from hub.inventory import build_inventory


def _mk_vault(tmp_path, host="box1") -> Path:
    vault = tmp_path / "vault"
    (vault / host).mkdir(parents=True)
    (vault / "vault.toml").write_text("version = 3\n", encoding="utf-8")

    # plugin 资产 + plugin-internal skill
    (vault / "shared" / "plugins" / "p1" / ".claude-plugin").mkdir(parents=True)
    (vault / "shared" / "plugins" / "p1" / "skills" / "beta").mkdir(parents=True)
    (vault / "shared" / "plugins" / "p1" / "skills" / "beta" / "SKILL.md").write_text(
        "# beta\n", encoding="utf-8")
    (vault / "shared" / "plugins" / "manifest.toml").write_text(
        '[p1]\nplatforms=["claude","codex","opencode","dsh"]\n', encoding="utf-8")

    # standalone skill
    (vault / "shared" / "skills" / "alpha").mkdir(parents=True)
    (vault / "shared" / "skills" / "alpha" / "SKILL.md").write_text(
        "# alpha\n", encoding="utf-8")

    # memory
    (vault / "shared" / "memory").mkdir(parents=True)
    (vault / "shared" / "memory" / "m1.md").write_text(
        "---\nname: m1\ndescription: d\nmetadata:\n  type: reference\n"
        "  scope: [global]\n---\n正文\n", encoding="utf-8")

    home = tmp_path / "home"
    (vault / host / "device.toml").write_text(
        f'class=["work"]\nprojects=[]\n[paths]\n'
        f'CLAUDE_HOME="{home.as_posix()}/.claude"\n'
        f'AGENTS_HOME="{home.as_posix()}/.agents"\n'
        f'OPENCODE_CONFIG="{home.as_posix()}/.config/opencode/opencode.json"\n'
        f'DSH_HOME="{home.as_posix()}/.dsh"\n'
        f'DSH_PROFILE="headless"\n'
        '[plugins.claude]\nenabled=["p1"]\n'
        '[plugins.codex]\nenabled=["p1"]\n'
        '[plugins.opencode]\nenabled=["p1"]\n'
        '[plugins.dsh]\nenabled=["p1"]\n',
        encoding="utf-8")
    return vault


def _fake_run_cli(argv, runner=None):
    cmd = argv if isinstance(argv, list) else getattr(argv, "argv", [])
    s = " ".join(cmd)
    if s == "claude plugin list --json":
        return CliResult(0, "[]", "")
    if s == "claude plugin marketplace list --json":
        return CliResult(0, "[]", "")
    if s == "codex plugin list --json":
        return CliResult(0, '{"installed":[]}', "")
    if s == "codex plugin marketplace list --json":
        return CliResult(0, '{"marketplaces":[]}', "")
    return CliResult(0, "ok", "")


def _patch_cli(monkeypatch):
    import hub.plugin_cli
    monkeypatch.setattr(hub.plugin_cli, "run_cli", _fake_run_cli)


def test_inventory_returns_parsable_json_structure(tmp_path, monkeypatch):
    vault = _mk_vault(tmp_path)
    _patch_cli(monkeypatch)
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hubhome"))

    data = build_inventory(vault, "box1", None)
    assert json.dumps(data, ensure_ascii=False)  # serializable
    assert data["vault"].endswith("vault")
    assert data["host"] == "box1"
    assert {"assets", "matrix", "warnings"} <= set(data)
    assert isinstance(data["assets"], list) and isinstance(data["matrix"], list)

    ids = {a["id"] for a in data["assets"]}
    assert {"plugin:p1", "skill:p1:beta", "skill:standalone:alpha", "memory:m1"} <= ids


def test_plugin_cells_have_expected_shape(tmp_path, monkeypatch):
    vault = _mk_vault(tmp_path)
    _patch_cli(monkeypatch)
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hubhome"))

    data = build_inventory(vault, "box1", None)
    plugin = next(a for a in data["assets"] if a["id"] == "plugin:p1")
    assert plugin["type"] == "plugin"
    assert plugin["plugin"] is None and plugin["skill_origin"] is None
    assert set(plugin["harnesses"]) == {"claude", "codex", "opencode", "dsh"}
    for tool, cell in plugin["harnesses"].items():
        assert set(cell) == {"harness", "desired", "actual", "health", "control", "detail"}
        assert cell["harness"] == tool
        assert cell["control"] == "direct"


def test_plugin_internal_skill_control_mapping(tmp_path, monkeypatch):
    vault = _mk_vault(tmp_path)
    _patch_cli(monkeypatch)
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hubhome"))

    data = build_inventory(vault, "box1", None)
    skill = next(a for a in data["assets"] if a["id"] == "skill:p1:beta")
    assert skill["skill_origin"] == "plugin-internal"
    assert skill["plugin"] == "p1"
    assert skill["harnesses"]["claude"]["control"] == "plugin"
    assert skill["harnesses"]["codex"]["control"] == "plugin"
    assert skill["harnesses"]["opencode"]["control"] == "direct"
    assert skill["harnesses"]["dsh"]["control"] == "direct"


def test_standalone_skill_and_dsh_unmanaged(tmp_path, monkeypatch):
    vault = _mk_vault(tmp_path)
    _patch_cli(monkeypatch)
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hubhome"))

    data = build_inventory(vault, "box1", None)
    skill = next(a for a in data["assets"] if a["id"] == "skill:standalone:alpha")
    assert skill["skill_origin"] == "standalone"
    assert skill["harnesses"]["dsh"]["control"] == "unmanaged"
    assert skill["harnesses"]["dsh"]["health"] == "unknown"
    assert all(h["control"] == "direct" for h in (skill["harnesses"]["claude"],
                                                  skill["harnesses"]["codex"],
                                                  skill["harnesses"]["opencode"]))


def test_memory_cells_are_readonly(tmp_path, monkeypatch):
    vault = _mk_vault(tmp_path)
    _patch_cli(monkeypatch)
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hubhome"))

    # claude 视图已含 m1；其它工具视图缺失 → actual false
    view = tmp_path / "hubhome" / "views" / "claude" / "MEMORY.md"
    view.parent.mkdir(parents=True)
    view.write_text("- [m1](<C:/vault/shared/memory/m1.md>)\n", encoding="utf-8")

    data = build_inventory(vault, "box1", None)
    mem = next(a for a in data["assets"] if a["id"] == "memory:m1")
    assert mem["type"] == "memory"
    assert mem["scope"] == ["global"]
    assert all(cell["control"] == "readonly" for cell in mem["harnesses"].values())
    assert mem["harnesses"]["claude"]["actual"] is True
    assert mem["harnesses"]["claude"]["desired"] is True
    assert mem["harnesses"]["codex"]["actual"] is False
    assert mem["harnesses"]["codex"]["desired"] is True




def test_inventory_survives_cli_unavailable(tmp_path, monkeypatch):
    vault = _mk_vault(tmp_path)
    import hub.plugin_cli
    from hub.plugin_cli import CliUnavailable

    def boom(argv, runner=None):
        raise CliUnavailable("fake CLI unavailable")

    monkeypatch.setattr(hub.plugin_cli, "run_cli", boom)
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hubhome"))

    data = build_inventory(vault, "box1", None)
    assert data["warnings"], "CLI 不可用应写入 warnings"
    plugin = next(a for a in data["assets"] if a["id"] == "plugin:p1")
    assert plugin["harnesses"]["claude"]["health"] == "unknown"
    assert plugin["harnesses"]["claude"]["actual"] is None
    # 其它资产仍照常组装
    assert any(a["id"] == "memory:m1" for a in data["assets"])

def test_cli_inventory_json_envelope(tmp_path, monkeypatch, capsys):
    vault = _mk_vault(tmp_path)
    _patch_cli(monkeypatch)
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hubhome"))

    rc = main(["inventory", "--vault", str(vault), "--host", "box1", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    envelope = json.loads(out)
    assert envelope["ok"] is True
    assert envelope["error"] is None
    assert envelope["data"]["vault"].endswith("vault")
    assert envelope["data"]["host"] == "box1"
    assert isinstance(envelope["meta"]["warnings"], list)
