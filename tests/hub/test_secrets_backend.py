import pytest
from hub.secrets_store import SecretsError
from hub.secrets_backend import parse_ref, resolve_ref, resolve_env

DOC = """---
name: demo
description: d
---

## fields

k1 = v1
k2 = v2
"""

@pytest.fixture
def root(tmp_path):
    (tmp_path / "demo.md").write_text(DOC, encoding="utf-8")
    return tmp_path

def test_parse_ok():
    assert parse_ref("hub://secrets/aliyun-oss-picgo/accessKeyId") == (
        "aliyun-oss-picgo", "accessKeyId")

@pytest.mark.parametrize("bad", [
    "hub://secrets/a", "hub://secrets/a/b/c", "hub://other/a/b",
    "secrets/a/b", "hub://secrets//b", "hub://secrets/../x/y",
    "hub://secrets/.unlock/token", "", "hub://secrets/a/",
])
def test_parse_refuses(bad):
    with pytest.raises(SecretsError):
        parse_ref(bad)

def test_resolve_ok(root):
    assert resolve_ref(root, "hub://secrets/demo/k1") == "v1"

def test_resolve_missing_field(root):
    with pytest.raises(SecretsError):
        resolve_ref(root, "hub://secrets/demo/nope")

def test_resolve_env(root):
    got = resolve_env(root, {"A": "hub://secrets/demo/k1", "B": "hub://secrets/demo/k2"})
    assert got == {"A": "v1", "B": "v2"}

def test_resolve_env_refuses_case_collision(root):
    # Windows 环境变量名大小写不敏感：A 与 a 同时声明是配置错误，必须炸
    with pytest.raises(SecretsError):
        resolve_env(root, {"A": "hub://secrets/demo/k1", "a": "hub://secrets/demo/k2"})

def test_resolve_env_refuses_bad_var_name(root):
    for bad in ("A=B", "A\x00B", ""):
        with pytest.raises(SecretsError):
            resolve_env(root, {bad: "hub://secrets/demo/k1"})

def test_error_never_contains_value(root):
    try:
        resolve_ref(root, "hub://secrets/demo/nope")
    except SecretsError as e:
        assert "v1" not in str(e) and "v2" not in str(e)