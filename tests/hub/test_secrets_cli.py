import pytest
from hub.secrets_store import SecretsError
from hub.secrets_cli import human_only
from hub import secrets_cli
from hub.cli import build_parser


class _S:
    """假的 stdout：有区分度的只是 isatty()，但要顶替 sys.stdout 就得接得住 print()。"""

    def __init__(self, tty):
        self._tty = tty
        self.buf = []

    def isatty(self):
        return self._tty

    def write(self, s):
        self.buf.append(s)
        return len(s)

    def flush(self):
        pass


def test_human_only_refuses_when_stdout_not_tty(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    with pytest.raises(SecretsError):
        human_only()


def test_human_only_passes_in_terminal(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    human_only()                    # 不抛


def test_human_only_never_uses_stdin_isatty(monkeypatch):
    """实测 stdin.isatty() 在 AI 工具下是 True——用它当判据等于没写（spec §6.7.3.2）。"""
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    monkeypatch.setattr(sys, "stdin", _S(True))     # 故意把 stdin 摆成"像终端"
    with pytest.raises(SecretsError):
        human_only()                                 # 仍然必须拒


def test_human_only_error_points_at_exec():
    """拒绝必须给出路，否则 AI 只会去想别的绕法（spec §6.2）。"""
    import sys

    class _NoTty:
        def isatty(self):
            return False

    orig = sys.stdout
    sys.stdout = _NoTty()
    try:
        with pytest.raises(SecretsError) as ei:
            human_only()
    finally:
        sys.stdout = orig
    assert "exec" in str(ei.value)


def test_exec_does_not_require_tty(monkeypatch, tmp_path):
    """exec 是给 AI 的那条通道，不设自守。"""
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    # exec 路径不调用 human_only
    assert "human_only" not in secrets_cli.cmd_exec.__code__.co_names


def test_run_and_render_do_require_tty():
    """run / render 的承重闸就长在进程里——hook 的命令串匹配枚举不完（spec §6.7.3.1）。"""
    assert "human_only" in secrets_cli.cmd_run.__code__.co_names
    assert "human_only" in secrets_cli.cmd_render.__code__.co_names


def test_render_has_no_out_option():
    """`render --out <工作区路径>` 正是 spec §5.4 那个洞：AI 指个落点再 Read 一遍就完了。
    修法不是"校验 --out 指向哪"，是**根本不提供这个参数**。"""
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["secrets", "render", "--profile", "x", "--out", "y.txt"])


def test_secrets_needs_no_vault():
    """密钥库与金库无关，secrets 不许跟着 common 吃 --vault。"""
    ns = build_parser().parse_args(["secrets", "exec", "ossutil", "cp", "a", "oss://b/"])
    assert ns.profile == "ossutil" and ns.args == ["cp", "a", "oss://b/"]
    assert not hasattr(ns, "vault")


def test_exec_tail_args_may_look_like_options():
    """`--force` 这种尾参必须原样传给 profile，不能被 argparse 抢走。"""
    ns = build_parser().parse_args(["secrets", "exec", "ossutil", "cp", "--force", "a"])
    assert ns.args == ["cp", "--force", "a"]


def test_run_argv_after_double_dash():
    ns = build_parser().parse_args(
        ["secrets", "run", "--profile", "ossutil", "--", "cmd", "/c", "echo", "%TOK%"])
    assert ns.profile == "ossutil"
    assert [a for a in ns.argv if a != "--"] == ["cmd", "/c", "echo", "%TOK%"]


def test_unlock_minutes_default_is_short():
    ns = build_parser().parse_args(["secrets", "unlock"])
    assert 1 <= ns.minutes <= 60          # 没有"一直开着"的档位
