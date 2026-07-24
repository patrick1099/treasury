"""够不着远端要自己重试;内容冲突一次都不许重试。

实测(2026-07-24,本机走代理):金库是私有仓,每次操作多吃一轮 401 + 带凭据重来,
单次失败率约 1/6(同一时段同一条代理,公开仓 6/6 全过)。人被迫手动重跑 `hub sync`,
而重跑本身几乎总是成功——那就该由它自己重。
"""
import subprocess
from pathlib import Path

import pytest

import hub.backend as backend
from hub.backend import GitBackend, ConflictError, RemoteUnavailable


class _Fake:
    """假的 git:按剧本决定第 N 次调用是成功还是失败。"""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    # 注:monkeypatch 到类上的是**实例**不是函数,没有描述符绑定,所以收不到 self。
    def __call__(self, *args, check=True):
        self.calls.append(args)
        if args and args[0] == "remote":
            return subprocess.CompletedProcess([], 0, "origin\n", "")
        if args and args[0] == "diff":               # _conflicted_files
            return subprocess.CompletedProcess([], 0, self.conflict, "")
        if "pull" in args or "push" in args:
            ok = self.script.pop(0) if self.script else True
            return subprocess.CompletedProcess([], 0 if ok else 1, "", "schannel: handshake 挂了")
        return subprocess.CompletedProcess([], 0, "", "")

    conflict = ""


@pytest.fixture
def fast(monkeypatch):
    slept = []
    monkeypatch.setattr(backend.time, "sleep", lambda s: slept.append(s))
    return slept


def _install(monkeypatch, fake):
    monkeypatch.setattr(GitBackend, "_run", fake)
    monkeypatch.setattr(backend, "tracked_gitlinks", lambda repo: [])   # 本文件不测这个闸


def _net_flags(args) -> bool:
    return "http.lowSpeedLimit=1000" in args and "http.lowSpeedTime=60" in args


def test_transient_pull_failure_is_retried(monkeypatch, fast):
    fake = _Fake([False, False, True])
    _install(monkeypatch, fake)
    GitBackend(Path("x")).acquire()                  # 不抛 = 第三次成了
    pulls = [a for a in fake.calls if "pull" in a]
    assert len(pulls) == 3
    assert fast == [3, 8], "两次重试之间要退避,别贴着重打"


def test_persistent_pull_failure_still_raises(monkeypatch, fast):
    fake = _Fake([False, False, False])
    _install(monkeypatch, fake)
    with pytest.raises(RemoteUnavailable):
        GitBackend(Path("x")).acquire()
    assert len([a for a in fake.calls if "pull" in a]) == 3, "重试次数要有上限"


def test_merge_conflict_is_never_retried(monkeypatch, fast):
    """冲突重试一百次也还是冲突,只会拖慢报错。"""
    fake = _Fake([False, True, True])
    fake.conflict = "shared/memory/a.md\n"
    _install(monkeypatch, fake)
    with pytest.raises(ConflictError) as ei:
        GitBackend(Path("x")).acquire()
    assert not isinstance(ei.value, RemoteUnavailable)
    assert len([a for a in fake.calls if "pull" in a]) == 1
    assert fast == []


def test_push_is_retried_too(monkeypatch, fast):
    fake = _Fake([False, True])
    _install(monkeypatch, fake)
    GitBackend(Path("x")).publish("m")
    assert len([a for a in fake.calls if "push" in a]) == 2


def test_network_ops_carry_the_low_speed_guard(monkeypatch, fast):
    """挂死的连接默认要卡 300s,那样重试就是纯受罪。"""
    fake = _Fake([True])
    _install(monkeypatch, fake)
    GitBackend(Path("x")).acquire()
    assert all(_net_flags(a) for a in fake.calls if "pull" in a)
    fake2 = _Fake([True])
    _install(monkeypatch, fake2)
    GitBackend(Path("x")).publish("m")
    assert all(_net_flags(a) for a in fake2.calls if "push" in a)
