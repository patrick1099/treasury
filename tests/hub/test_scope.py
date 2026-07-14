import pytest
from hub.scope import parse_scope, lint_scope, ScopeError

# 提取器对 scope 只做**校验**(hub sync 的 lint),不做匹配 —— 匹配是加载器(项目 C)
# 的判断题,见 SCHEMA §2。scope_matches() 是落地层的遗物,已随落地层一起删掉,
# 所以这里也不再测"哪条记忆命中哪台机"。

def test_same_dim_is_or():
    assert parse_scope(["device:work", "device:home"]) == {"device": {"work", "home"}}

def test_cross_dim_is_and():
    assert parse_scope(["project:xinao", "tool:claude"]) == {
        "project": {"xinao"}, "tool": {"claude"}}

def test_global_alone_yields_no_dims():
    assert parse_scope(["global"]) == {}

def test_global_must_be_alone():
    with pytest.raises(ScopeError):
        parse_scope(["global", "tool:claude"])
    assert lint_scope(["global", "tool:claude"]) != []
    assert lint_scope(["project:xinao", "tool:claude"]) == []

def test_unknown_dimension_rejected():
    assert lint_scope(["weird:x"]) != []

def test_malformed_predicate_rejected():
    assert lint_scope(["device:"]) != []      # 有维度没值
    assert lint_scope(["device"]) != []       # 根本没有冒号
