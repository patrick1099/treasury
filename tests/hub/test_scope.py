# tests/hub/test_scope.py（整体替换：旧用例断言 device: 合法，已作废）
import pytest
from hub.scope import parse_scope, scope_matches, ScopeError

def test_class_replaces_device():
    dims = parse_scope(["class:work"])
    assert dims == {"class": {"work"}}

def test_old_device_token_rejected():
    with pytest.raises(ScopeError):
        parse_scope(["device:work"])          # 旧语法，明确拒绝

def test_global_must_be_alone():
    with pytest.raises(ScopeError):
        parse_scope(["global", "tool:claude"])

def test_unknown_prefix_and_empty_rejected():
    for bad in (["projet:xinao"], ["class:"], []):
        with pytest.raises(ScopeError):
            parse_scope(bad)

# ---- 匹配 ----
def _m(scope, classes, projects, tool):
    return scope_matches(parse_scope(scope), classes, projects, tool)

def test_global_matches_everything():
    assert _m(["global"], [], [], "claude") is True

def test_tool_only_matches_all_devices_that_tool():
    assert _m(["tool:claude"], ["work"], ["x"], "claude") is True
    assert _m(["tool:claude"], ["work"], ["x"], "codex") is False

def test_class_or_project_within_device_dimension():
    # class 与 project 同维 OR：命中任一即可
    assert _m(["class:work", "project:xinao"], ["home"], ["xinao"], "claude") is True
    assert _m(["class:work", "project:xinao"], ["work"], ["other"], "claude") is True
    assert _m(["class:work", "project:xinao"], ["home"], ["other"], "claude") is False

def test_device_and_tool_are_anded():
    assert _m(["project:xinao", "tool:codex"], [], ["xinao"], "codex") is True
    assert _m(["project:xinao", "tool:codex"], [], ["xinao"], "claude") is False
    assert _m(["project:xinao", "tool:codex"], [], ["other"], "codex") is False
