# tests/hub/test_platforms.py —— 平台注册表的结构测试
#
# 规矩写在文档里拦不住漂移，这里拦：
#   ① 成员清单与能力只从注册表派生——塞一个假平台，各入口都看得到它；
#   ② 停用的平台不 import、不探测、不写，也不会被当成"插件不要了"去卸载；
#   ③ 启用的平台坏了只报它自己，聚合诊断照常，写命令零写入并返回非零；
#   ④ device.toml 的 platforms 缺省 = 全开，[] = 全停，写错类型/名字明确报错。
import io
import json
import sys
import types
from pathlib import Path

import pytest

from hub import cliout, platforms
from hub.cli import main, build_parser
from hub.model import DeviceProfile
from hub.platforms import (PlatformConfigError, PlatformDisabled, PlatformUnavailable,
                           enabled_names)
from hub.platforms.base import Platform, RegisterPlan
from hub.vault import load_device

IMPL_MODULES = ("hub.platforms.opencode", "hub.platforms.dsh",
                "hub.opencode_skills", "hub.dsh_ops", "hub.opencode_cfg")


@pytest.fixture
def machine_out(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cliout, "_MACHINE_OUT", buf)
    return buf


@pytest.fixture
def machine_err(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cliout, "_MACHINE_ERR", buf)
    return buf


def _vault(tmp_path, *, platforms_line=None, skills=("alpha",)) -> Path:
    """金库 + 一台设备：四个平台的路径都配上，dsh loader 源码**不存在**（本机真实状况）。"""
    v = tmp_path / "vault"
    (v / "box1").mkdir(parents=True)
    (v / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    for name in skills:
        d = v / "shared" / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.json").write_text("{}", encoding="utf-8")
    (home / ".dsh" / "profiles" / "headless").mkdir(parents=True)
    head = f"platforms = {json.dumps(platforms_line)}\n" if platforms_line is not None else ""
    (v / "box1" / "device.toml").write_text(
        head + 'class=[]\nprojects=[]\n[paths]\n'
        f'VAULT="{v.as_posix()}"\n'
        f'CLAUDE_HOME="{(home / ".claude").as_posix()}"\n'
        f'CODEX_HOME="{(home / ".codex").as_posix()}"\n'
        f'AGENTS_HOME="{(home / ".agents").as_posix()}"\n'
        f'OPENCODE_CONFIG="{(home / ".config" / "opencode" / "opencode.json").as_posix()}"\n'
        f'DSH_HOME="{(home / ".dsh").as_posix()}"\n'
        'DSH_PROFILE="headless"\n', encoding="utf-8")
    return v


def _forget_impl_modules(monkeypatch):
    for name in IMPL_MODULES:
        if name in sys.modules:
            monkeypatch.delitem(sys.modules, name)


def _files_under(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*")) if root.exists() else []


# ---------------------------------------------------------------- ④ 配置

def test_platforms_missing_means_all(tmp_path):
    dev = load_device(_vault(tmp_path), "box1")
    assert enabled_names(dev) == platforms.all_names()


def test_platforms_empty_means_none(tmp_path):
    dev = load_device(_vault(tmp_path, platforms_line=[]), "box1")
    assert enabled_names(dev) == ()


def test_platforms_keep_registry_order(tmp_path):
    dev = load_device(_vault(tmp_path, platforms_line=["codex", "claude"]), "box1")
    assert enabled_names(dev) == ("claude", "codex")


@pytest.mark.parametrize("bad", ["claude", [1, 2], ["claude", "gemini"]])
def test_platforms_bad_value_is_rejected_at_load(tmp_path, bad):
    with pytest.raises(PlatformConfigError):
        load_device(_vault(tmp_path, platforms_line=bad), "box1")


# ---------------------------------------------------------------- ② 停用

def test_disabled_platforms_are_not_imported_probed_or_written(tmp_path, monkeypatch, machine_out,
                                                              machine_err):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path, platforms_line=["claude", "codex"])
    _forget_impl_modules(monkeypatch)
    rc = main(["register", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0, machine_err.getvalue().decode("utf-8")
    data = json.loads(machine_out.getvalue())["data"]
    assert "opencode_links" not in data and "dsh_loader" not in data
    for name in IMPL_MODULES:
        assert name not in sys.modules, f"停用的平台被 import 了：{name}"
    home = tmp_path / "home"
    assert (home / ".claude" / "skills" / "alpha").exists()          # 启用的照常
    assert (home / ".agents" / "skills" / "alpha").exists()
    assert _files_under(home / ".dsh") == ["profiles", str(Path("profiles/headless"))]
    assert (home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8") == "{}"
    views = tmp_path / ".hub" / "views"
    assert sorted(p.name for p in views.iterdir()) == ["claude", "codex"]


def test_status_check_passes_with_broken_platform_disabled(tmp_path, monkeypatch, machine_out,
                                                           machine_err):
    """本机的真实场景：dsh loader 源码缺失，把 dsh（和 opencode）停掉之后 status --check 回到健康。"""
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path, platforms_line=["claude", "codex"])
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=v, check=True)
    assert main(["register", "--vault", str(v), "--host", "box1", "--json"]) == 0
    machine_out.truncate(0); machine_out.seek(0)
    rc = main(["status", "--vault", str(v), "--host", "box1", "--check", "--json"])
    assert rc == 0, machine_err.getvalue().decode("utf-8")
    labels = " ".join(row[1] for row in json.loads(machine_out.getvalue())["data"]["health"]["rows"])
    assert "dsh" not in labels and "opencode" not in labels


def test_disabled_cli_platform_gets_no_plugin_actions(tmp_path):
    """平台停用 ≠ 插件不要了：不许为停用平台生成禁用/卸载动作，连它的 CLI 都不许碰。"""
    from tests.hub.test_plugin_register import _setup, make_runner
    from hub.plugin_ops import prepare_plugin_register
    dev = _setup(tmp_path, {"cjt": ["claude", "codex"]}, {"claude": ["cjt"], "codex": []})
    dev.platforms = ["claude"]
    calls = []
    inner = make_runner(inst_codex=[{"pluginId": "cjt@cjt", "version": "0.1.0", "enabled": True,
                                     "marketplaceName": "cjt", "source": {"path": "x"}}])

    def runner(argv):
        calls.append(argv[0])
        return inner(argv)
    plan = prepare_plugin_register(tmp_path, dev, runner=runner)
    assert "codex" not in calls
    assert not any(":codex:" in a.id for a in plan.actions)


def test_toggle_and_memory_read_refuse_disabled_platform(tmp_path, monkeypatch, machine_out,
                                                         machine_err):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path, platforms_line=["claude", "codex"])
    from hub.toggle_ops import toggle_asset
    with pytest.raises(PlatformDisabled):
        toggle_asset(v, "box1", "skill", "alpha", "opencode", True)
    rc = main(["memory-read", "--vault", str(v), "--host", "box1", "--tool", "dsh",
               "--name", "x", "--json"])
    assert rc == 1
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


def test_inventory_drops_disabled_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path, platforms_line=["claude"])
    from hub.inventory import build_inventory
    data = build_inventory(v, "box1", None)
    assert data["harnesses"] == ["claude"]
    assert all(set(a["harnesses"]) <= {"claude"} for a in data["assets"])


# ---------------------------------------------------------------- ③ 不可用

def test_unavailable_platform_blocks_register_with_zero_writes(tmp_path, monkeypatch, machine_out,
                                                               machine_err):
    """dsh 启用但 loader 源码缺失：register 报出原因、非零、一个字节都不写。"""
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path)                                     # 缺省 = 四个平台全开
    rc = main(["register", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    err = json.loads(machine_err.getvalue())["error"]
    assert err["code"] == "E_PLATFORM" and "dsh" in err["message"]
    assert _files_under(tmp_path / "home" / ".claude") == []
    assert not (tmp_path / ".hub").exists()


def test_unavailable_platform_isolated_in_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path)
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=v, check=True)
    rc = main(["status", "--vault", str(v), "--host", "box1"])
    out = capsys.readouterr().out
    assert rc == 0                                           # 不带 --check：只报不判
    assert "[unavailable]" in out and "dsh" in out
    assert "alpha" in out                                    # 其余平台照常检查


def test_unavailable_platform_is_unknown_column_in_inventory(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path)
    from hub.inventory import build_inventory
    data = build_inventory(v, "box1", None)
    skill = next(a for a in data["assets"] if a["id"] == "skill:standalone:alpha")
    assert skill["harnesses"]["dsh"]["health"] == "unknown"
    assert "loader" in skill["harnesses"]["dsh"]["detail"]
    assert skill["harnesses"]["claude"]["health"] != "unknown"
    assert any("dsh" in w for w in data["warnings"])


def test_adapter_import_failure_is_isolated(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(platforms.REGISTRY, "ghost", "hub.platforms._no_such_module")
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path, platforms_line=["claude", "ghost"])
    loaded = platforms.enabled(load_device(v, "box1"))
    assert [(x.name, x.adapter is None) for x in loaded] == [("claude", False), ("ghost", True)]
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=v, check=True)
    assert main(["status", "--vault", str(v), "--host", "box1"]) == 0
    out = capsys.readouterr().out
    assert "ghost" in out and "[unavailable]" in out and "alpha" in out
    assert main(["register", "--vault", str(v), "--host", "box1"]) == 1
    assert not (tmp_path / "home" / ".claude" / "skills").exists()   # 零写入


# ---------------------------------------------------------------- ① 从注册表派生

class _Fake(Platform):
    name = "fake"
    status_title = "fake 附加检查"
    status_key = "fake_rows"
    register_key = "fake_items"
    register_label = "fake 配置项"

    def __init__(self, home):
        self.home = home

    def skills_home(self, dev):
        return self.home / "skills"

    def prepare_register(self, vault_root, dev, hub_root):
        return RegisterPlan(ensured=["x"])

    def status_rows(self, vault_root, dev, hub_root):
        return [("ok", "fake 一切正常")]

    def standalone_skill_cell(self, ctx, state, name, src):
        return {"harness": "fake", "desired": True, "actual": True, "health": "ok",
                "control": "direct", "detail": "fake"}


@pytest.fixture
def fake_platform(tmp_path, monkeypatch):
    mod = types.ModuleType("fake_platform_adapter")
    mod.ADAPTER = _Fake(tmp_path / "fakehome")
    monkeypatch.setitem(sys.modules, "fake_platform_adapter", mod)
    monkeypatch.setitem(platforms.REGISTRY, "fake", "fake_platform_adapter")
    return mod.ADAPTER


def test_fake_platform_reaches_every_entry_point(tmp_path, monkeypatch, fake_platform, machine_out,
                                                 machine_err):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    v = _vault(tmp_path, platforms_line=["claude", "fake"])

    # CLI choices / scope 词表
    parser = build_parser()
    args = parser.parse_args(["toggle", "skill", "alpha", "fake", "on"])
    assert args.harness == "fake"
    from hub.scope import parse_scope
    assert parse_scope(["tool:fake"]) == {"tool": {"fake"}}

    # register：通用 skill 链接进它的 skills_home，附加计划计数进 JSON
    assert main(["register", "--vault", str(v), "--host", "box1", "--json"]) == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["fake_items"] == 1
    assert (tmp_path / "fakehome" / "skills" / "alpha").exists()
    assert (tmp_path / ".hub" / "views" / "fake" / "MEMORY.md").exists()

    # status：附加行按它声明的键出现
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=v, check=True)
    machine_out.truncate(0); machine_out.seek(0)
    assert main(["status", "--vault", str(v), "--host", "box1", "--json"]) == 0
    assert json.loads(machine_out.getvalue())["data"]["fake_rows"] == [["ok", "fake 一切正常"]]

    # inventory / memory-explain
    from hub.inventory import build_inventory
    inv = build_inventory(v, "box1", None)
    assert inv["harnesses"] == ["claude", "fake"]
    skill = next(a for a in inv["assets"] if a["id"] == "skill:standalone:alpha")
    assert skill["harnesses"]["fake"]["detail"] == "fake"
    from hub.memory_ops import explain_memories
    tools = [t["tool"] for t in explain_memories(v, load_device(v, "box1"), None)["tools"]]
    assert tools == ["claude", "fake"]


def test_callers_do_not_hardcode_platform_names():
    """拔插自查的自动版：调用方源码里不许再出现平台名单或按平台名分支。"""
    import re
    root = Path(__file__).resolve().parents[2] / "hub"
    callers = ["cli.py", "inventory.py", "toggle_ops.py", "status_report.py", "memwire.py",
               "memory_ops.py", "scope.py", "register.py", "plugin_ops.py", "plugin_cli.py"]
    names = "|".join(platforms.all_names())
    pattern = re.compile(rf'(==|!=|\bin)\s*\(?\s*"({names})"|\(\s*"({names})"\s*,\s*"({names})"')
    offenders = []
    for f in callers:
        for i, line in enumerate((root / f).read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if pattern.search(code) and "cli_dialect" not in code and 'd == "' not in code \
                    and 'd != "' not in code and 'dialect == "' not in code:
                offenders.append(f"{f}:{i}: {line.strip()}")
    # promote --tool 的 choices 是备份区目录名（另一条轴），不属于平台注册表
    offenders = [o for o in offenders if "pro.add_argument" not in o]
    assert offenders == []
