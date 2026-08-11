import json
import subprocess
import sys
from pathlib import Path
import pytest

HOOK = Path(__file__).resolve().parents[2] / "hub" / "hooks" / "secrets_guard.py"


def _raw(payload, env_extra=None):
    """**按原始 UTF-8 字节喂、按 UTF-8 解——绝不能用 `text=True`。**

    `text=True` 会让父子两头都用本机 locale（cp936）编解码，两边自洽，于是
    "hook 用 locale 解 stdin"这类 bug 在测试里**根本不会出现**。真机上 Claude Code
    送的是 UTF-8：2026-08-11 第一次挂上闸，第一条带中文的 Write payload 就
    JSONDecodeError → 顶层转 exit 2 → 把自己的工具调用拦死了。
    """
    import os
    env = dict(os.environ); env.update(env_extra or {})
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          capture_output=True, env=env)


def _run(payload, env_extra=None):
    from types import SimpleNamespace
    cp = _raw(payload, env_extra)
    return SimpleNamespace(returncode=cp.returncode,
                           stdout=cp.stdout.decode("utf-8"),
                           stderr=cp.stderr.decode("utf-8"))


def _decide(cp):
    return json.loads(cp.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.fixture
def sroot(tmp_path, monkeypatch):
    d = tmp_path / "secrets"; d.mkdir()
    (d / "demo.md").write_text("---\nname: demo\n---\n\n## fields\n\nk = v\n", encoding="utf-8")
    return d


def test_read_existing_denied(sroot):
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(sroot / "demo.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and _decide(cp) == "deny"


def test_read_with_token_asks(sroot):
    import time
    (sroot / ".unlock").write_text(str(int(time.time() + 600)), encoding="utf-8")
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(sroot / "demo.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "ask"


def test_expired_token_still_denies(sroot):
    import time
    (sroot / ".unlock").write_text(str(int(time.time() - 1)), encoding="utf-8")
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(sroot / "demo.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny"


def test_garbage_token_still_denies(sroot):
    (sroot / ".unlock").write_text("not-a-timestamp", encoding="utf-8")
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(sroot / "demo.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny"      # 读不懂令牌 = 没有令牌，不是有令牌


def test_write_new_file_asks(sroot):
    cp = _run({"tool_name": "Write", "tool_input": {"file_path": str(sroot / "brand-new.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "ask"          # 首次录入：拦写没意义，弹窗让用户看见存到哪


def test_symlink_bypass_blocked(tmp_path, sroot):
    link = tmp_path / "innocent.md"
    try:
        link.symlink_to(sroot / "demo.md")
    except OSError:
        pytest.skip("本机没有创建符号链接的权限")
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(link)}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny"         # guard.is_denied 的双查在这里兑现


def test_unrelated_path_allowed(tmp_path, sroot):
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "readme.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and cp.stdout.strip() == ""     # 不相干就别插嘴


@pytest.mark.parametrize("cmd", [
    "hub secrets unlock --minutes 10",
    "py -3 -m hub.cli secrets unlock --minutes 10",           # ← 本机的**真实**写法
    "python -m hub.cli secrets unlock",
    "py -3 C:/Users/huawei/ai-cli-migrate/hub/cli.py secrets unlock",
    "hub secrets run -- cmd /c echo %TOK%",
    "py -3 -m hub.cli secrets render --out x.txt",
])
def test_bash_denied_forms(sroot, cmd):
    cp = _run({"tool_name": "Bash", "tool_input": {"command": cmd}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny", cmd


def test_bash_exec_allowed(sroot):
    cp = _run({"tool_name": "Bash",
               "tool_input": {"command": "py -3 -m hub.cli secrets exec ossutil cp a oss://b/"}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and (cp.stdout.strip() == "" or _decide(cp) == "allow")


def test_bash_reading_secrets_by_type_denied(sroot):
    cp = _run({"tool_name": "Bash",
               "tool_input": {"command": f'cmd /c type "{sroot / "demo.md"}"'}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny"


@pytest.mark.parametrize("payload", [
    {"tool_name": "Grep", "tool_input": {"pattern": "secrets", "path": "."}},
    {"tool_name": "Bash", "tool_input": {"command": "grep -rn secrets ."}},
    {"tool_name": "Bash", "tool_input": {"command": "git log --oneline | head"}},
])
def test_no_false_positive(sroot, payload):
    """误伤会逼人把闸摘掉，闸就废了（spec §6.4）。裸词 `secrets` 必须放行。"""
    cp = _run(payload, {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and cp.stdout.strip() == ""


@pytest.mark.parametrize("cmd", [
    "echo hub://secrets/demo/k1 >> notes.md",
    "py -3 -m hub.cli secrets exec ossutil cp hub://secrets/demo/k1 oss://b/",
])
def test_hub_ref_is_not_a_path(sroot, cmd):
    """**`hub://secrets/<item>/<field>` 必须放行。**

    `Path("hub://secrets/demo/k1").parts` 里有一个字面 `secrets`，guard.is_denied 判它命中。
    可这正是本项目要推广的引用写法——命令串里出现它就被拒是纯误伤，而且是冲着
    我们自己的正解去的。URI 不是文件系统路径，扫描时必须先把带 scheme 的 token 摘掉。
    """
    cp = _run({"tool_name": "Bash", "tool_input": {"command": cmd}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and cp.stdout.strip() == "", cmd


@pytest.mark.parametrize("payload", [
    {"tool_name": "Write", "tool_input": {"file_path": "C:/tmp/x.py",
                                          "content": "# 中文注释，带全角标点\n"}},
    {"tool_name": "Bash", "tool_input": {"command": "git commit -m '修掉编码坑'"}},
    {"tool_name": "Grep", "tool_input": {"pattern": "密钥明文", "path": "hub"}},
])
def test_non_ascii_payload_is_parsed(sroot, payload):
    """**这条是用真机事故换来的。**

    Claude Code 送 UTF-8，Windows 的 sys.stdin 按 cp936 解——只要 payload 里有一个
    中文字符就 JSONDecodeError，而顶层 fail-closed 会把它变成 exit 2，于是**每一条
    带中文的工具调用都被自己的闸拦死**。日常写中文注释、中文 commit message 的人，
    等于挂上闸就没法干活了。
    """
    cp = _run(payload, {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == ""          # 不相干路径，不该插嘴


def test_reason_is_utf8_bytes_on_the_wire(sroot):
    """判定理由是中文，stdout 必须是 UTF-8 字节。

    走 sys.stdout 文本流的话，本机 cp936 轻则让 Claude Code 收到乱码理由，
    重则 UnicodeEncodeError —— 那会让这次判定退 1，也就是**静默放行**。
    """
    cp = _raw({"tool_name": "Read", "tool_input": {"file_path": str(sroot / "demo.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0
    assert "密钥明文读不了".encode("utf-8") in cp.stdout          # 线上就是 UTF-8 字节
    d = json.loads(cp.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert d["permissionDecision"] == "deny" and "hub://" in d["permissionDecisionReason"]


def test_malformed_input_exits_2(sroot):
    import os
    env = dict(os.environ); env["HUB_SECRETS_ROOT"] = str(sroot)
    cp = subprocess.run([sys.executable, str(HOOK)], input=b"{not json",
                        capture_output=True, env=env)
    assert cp.returncode == 2        # **不是 1** —— exit 1 是非阻断，工具照跑


def test_guard_exception_exits_2(sroot):
    """判定逻辑一崩就静默放行是最致命的坑（spec §6.1）。"""
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": None}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 2


def test_non_dict_tool_input_exits_2(sroot):
    cp = _run({"tool_name": "Read", "tool_input": "oops"},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 2


def test_hook_does_not_import_backend():
    """hook 每次工具调用都跑；也绝不能把明文层拖进来。"""
    src = HOOK.read_text(encoding="utf-8")
    assert "secrets_backend" not in src
    assert "read_source_text" not in src      # 判定者不是被判定者
