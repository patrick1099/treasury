import time
import pytest
from hub.secrets_store import SecretsError
from hub import secrets_unlock as U


class _S:
    """假的 stdout。

    有区分度的只是 `isatty()`，但它要顶替 `sys.stdout`，就得能接住 `print()`——
    issue_token 会先打印一句提示，只有 isatty() 的桩会炸成 AttributeError。
    """

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


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_SECRETS_ROOT", str(tmp_path))
    return tmp_path


def test_refuses_without_tty(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    with pytest.raises(SecretsError):
        U.issue_token(10)
    assert not U.token_path().exists()            # fail-closed：不产生令牌


def test_refuses_when_console_unreadable(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: (_ for _ in ()).throw(OSError("no console")))
    with pytest.raises(SecretsError):
        U.issue_token(10)
    assert not U.token_path().exists()


def test_refuses_on_wrong_phrase(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: "nope")
    with pytest.raises(SecretsError):
        U.issue_token(10)
    assert not U.token_path().exists()


def test_issues_on_correct_phrase(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: U.CONFIRM_PHRASE)
    U.issue_token(10)
    assert U.token_valid()


def test_expires(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: U.CONFIRM_PHRASE)
    U.issue_token(10)
    assert U.token_valid(now=time.time() + 9 * 60)
    assert not U.token_valid(now=time.time() + 11 * 60)      # 时间边界


def test_minutes_out_of_range_refused(root, monkeypatch):
    """没有"一直开着"的档位，也没有"开一整天"。"""
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: U.CONFIRM_PHRASE)
    for bad in (0, -1, U.MAX_MINUTES + 1, 10.0, True, "10"):
        with pytest.raises(SecretsError):
            U.issue_token(bad)
        assert not U.token_path().exists()


def test_no_forever_option():
    import inspect
    src = inspect.getsource(U)
    assert "--forever" not in src and "minutes=0" not in src   # 没有"一直开着"的档位


def test_garbage_token_is_invalid(root):
    U.token_path().write_text("not-a-timestamp", encoding="utf-8")
    assert U.token_valid() is False                            # 解析不了 = 无效，不是有效


def test_token_valid_uses_bare_read(root):
    """hook 是判定者不是被判定者：走 guard.read_source_text 会命中 secrets 黑名单
    把自己挡死（spec §6.7.3.4 第 1 条）。"""
    import inspect
    assert "read_source_text" not in inspect.getsource(U.token_valid)


def test_unlock_is_not_a_secret_item(root, monkeypatch):
    """`.unlock` 不能被当成一条可引用的密钥（spec §6.7.3.4 第 2 条）。"""
    from hub.secrets_store import iter_items
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: U.CONFIRM_PHRASE)
    U.issue_token(10)
    assert U.token_path().name not in iter_items(root)
    assert ".unlock" not in [f"{i}.md" for i in iter_items(root)]
