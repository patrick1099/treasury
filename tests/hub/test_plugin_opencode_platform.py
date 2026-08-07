"""manifest 里出现 platforms = [..., "opencode"] 时，走 CLI 的那三条流程必须原样不受影响。

opencode 没有插件安装通道（它拿插件 skill 是靠 opencode_skills 活链），所以 plugin_ops
的 NEEDED 里根本没有 "opencode" 这个键。没有 _cli_platforms 这道过滤的话，
`NEEDED[tool]` 会直接 KeyError，把 register / refresh / status --check 整条打挂——
而且是在给 manifest 加平台的那一刻才炸，症状离原因很远。这组测试把它钉死。
"""
import json
import pytest
from hub.plugin_ops import (prepare_plugin_register, prepare_plugin_refresh,
                            plugin_health, _cli_platforms, CLI_PLATFORMS)
from hub.plugin_manifest import PluginEntry
from tests.hub.test_plugin_register import _setup, make_runner, _ids

def test_cli_platforms_filters_opencode_out():
    e = PluginEntry("p", ["claude", "codex", "opencode"], None, None)
    assert _cli_platforms(e) == ["claude", "codex"]
    assert "opencode" not in CLI_PLATFORMS

def test_register_plan_identical_with_and_without_opencode_in_manifest(tmp_path, tmp_path_factory):
    """加了 opencode 之后，claude/codex 的动作清单必须**一个字不差**。"""
    a = tmp_path_factory.mktemp("without")
    dev_a = _setup(a, {"cjt": ["claude", "codex"]}, {"claude": ["cjt"], "codex": ["cjt"]})
    plan_a = prepare_plugin_register(a, dev_a, runner=make_runner())

    b = tmp_path_factory.mktemp("with")
    dev_b = _setup(b, {"cjt": ["claude", "codex", "opencode"]},
                   {"claude": ["cjt"], "codex": ["cjt"], "opencode": ["cjt"]})
    plan_b = prepare_plugin_register(b, dev_b, runner=make_runner())

    assert _ids(plan_a) == _ids(plan_b)

def test_opencode_only_plugin_produces_no_cli_actions(tmp_path):
    """只面向 opencode 的插件：CLI 侧完全没有它的动作，也不去探 opencode 有没有 CLI。"""
    dev = _setup(tmp_path, {"solo": ["opencode"]}, {"opencode": ["solo"]})
    probed = []
    def runner(argv):
        probed.append(" ".join(argv))
        return make_runner()(argv)
    plan = prepare_plugin_register(tmp_path, dev, runner=runner)
    assert plan.actions == []
    assert not any("opencode" in c for c in probed)      # 没拿 opencode 当 CLI 探过

def test_refresh_does_not_keyerror_on_opencode(tmp_path):
    dev = _setup(tmp_path, {"cjt": ["claude", "opencode"]}, {"claude": ["cjt"]})
    prepare_plugin_refresh(tmp_path, dev, runner=make_runner())      # 不抛即通过

def test_health_reports_only_cli_platforms(tmp_path):
    dev = _setup(tmp_path, {"cjt": ["claude", "codex", "opencode"]},
                 {"claude": ["cjt"], "codex": ["cjt"], "opencode": ["cjt"]})
    rows = plugin_health(tmp_path, dev, runner=make_runner())
    assert sorted(h.tool for h in rows) == ["claude", "codex"]
