import pytest
from hub.scope import parse_scope, scope_matches, lint_scope, ScopeError
from hub.model import Target

def T(classes=(), project=None, tool="claude"):
    return Target(frozenset(classes), project, tool)

def test_global_matches_everything():
    assert scope_matches(["global"], T(tool="codex")) is True

def test_same_dim_is_or():
    assert parse_scope(["device:work", "device:home"]) == {"device": {"work", "home"}}
    assert scope_matches(["device:work", "device:home"], T(classes=["home"])) is True
    assert scope_matches(["device:work", "device:home"], T(classes=["lab"])) is False

def test_cross_dim_is_and():
    s = ["project:xinao", "tool:claude"]
    assert scope_matches(s, T(project="xinao", tool="claude")) is True
    assert scope_matches(s, T(project="xinao", tool="codex")) is False  # Claude 专属不漏给 Codex

def test_absent_dim_unrestricted():
    assert scope_matches(["tool:claude"], T(project="anything", tool="claude")) is True

def test_global_must_be_alone():
    with pytest.raises(ScopeError):
        parse_scope(["global", "tool:claude"])
    assert lint_scope(["global", "tool:claude"]) != []
    assert lint_scope(["project:xinao", "tool:claude"]) == []

def test_unknown_dimension_rejected():
    assert lint_scope(["weird:x"]) != []
