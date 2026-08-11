import os
import sys
import pytest
from hub.secrets_profile import Profile
from hub.secrets_run import redact_bytes, run_profile

DOC = """---
name: demo
description: d
---

## fields

k1 = s3cr3t-VALUE-xyz
"""

@pytest.fixture
def root(tmp_path):
    (tmp_path / "demo.md").write_text(DOC, encoding="utf-8")
    return tmp_path

def _py_profile(tmp_path, script: str) -> Profile:
    """当前解释器 + 一个真实入口脚本 = 固定启动链，形状与 node.exe + 入口脚本一致。

    **不能写成 `[sys.executable, "-c", script]`**：check_argv 要求启动链每一段都是
    存在的绝对路径，`-c` 第一个就过不去。这正是"启动链写死、AI 只能追加尾参"的
    直接后果——测试也得照这个形状搭，否则测的就不是真实通路。
    """
    entry = tmp_path / "entry.py"
    entry.write_text(script, encoding="utf-8")
    return Profile(name="t", argv=[sys.executable, str(entry)],
                   env={"TOK": "hub://secrets/demo/k1"},
                   allow_subcommands=["go"], arg_pattern="^[A-Za-z0-9._/:@=+-]*$")

def test_redact_exact_only():
    assert redact_bytes(b"a s3cr3t b", ["s3cr3t"]) == b"a <redacted> b"
    assert redact_bytes(b"s3-cr3t", ["s3cr3t"]) == b"s3-cr3t"     # 变形挡不住，这是已知局限

def test_value_reaches_child_verbatim(root):
    p = _py_profile(root, "import os,sys; sys.stdout.write(str(len(os.environ['TOK'])))")
    r = run_profile(p, ["go"], root)
    assert r.rc == 0 and r.out.strip() == str(len("s3cr3t-VALUE-xyz"))   # 长度对 → 逐字符保真

def test_stdout_redacted(root):
    p = _py_profile(root, "import os,sys; sys.stdout.write(os.environ['TOK'])")
    r = run_profile(p, ["go"], root)
    assert "s3cr3t-VALUE-xyz" not in r.out and "<redacted>" in r.out

def test_stderr_redacted_on_nonzero(root):
    p = _py_profile(root, "import os,sys; sys.stderr.write(os.environ['TOK']); sys.exit(3)")
    r = run_profile(p, ["go"], root)
    assert r.rc == 3 and "s3cr3t-VALUE-xyz" not in r.err

def test_timeout_output_redacted(root):
    p = _py_profile(root, "import os,sys,time; sys.stdout.write(os.environ['TOK']); "
                    "sys.stdout.flush(); time.sleep(30)")
    r = run_profile(p, ["go"], root, timeout=2)
    assert r.rc != 0 and "s3cr3t-VALUE-xyz" not in r.out

def test_undecodable_output_redacted(root):
    p = _py_profile(root, "import os,sys; sys.stdout.buffer.write(b'\\xff\\xfe' + "
                    "os.environ['TOK'].encode())")
    r = run_profile(p, ["go"], root)
    assert "s3cr3t-VALUE-xyz" not in r.out          # 解码失败路径也要先遮罩

def test_value_not_in_argv(root, monkeypatch):
    seen = {}
    import subprocess
    real = subprocess.run
    def spy(argv, **kw):
        seen["argv"] = argv
        return real(argv, **kw)
    monkeypatch.setattr(subprocess, "run", spy)
    run_profile(_py_profile(root, "pass"), ["go"], root)
    assert all("s3cr3t-VALUE-xyz" not in a for a in seen["argv"])

def test_parent_environ_untouched(root):
    before = dict(os.environ)
    run_profile(_py_profile(root, "pass"), ["go"], root)
    assert dict(os.environ) == before and "TOK" not in os.environ

def test_no_temp_file_left(root, tmp_path):
    import tempfile
    before = set(os.listdir(tempfile.gettempdir()))
    run_profile(_py_profile(root, "pass"), ["go"], root)
    assert set(os.listdir(tempfile.gettempdir())) == before