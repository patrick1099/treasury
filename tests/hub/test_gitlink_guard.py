"""金库里绝不能出现 gitlink——以及出现了要能修回来。

真机事故(2026-07-24):有人把一个带 `.git` 的插件目录放进 shared/plugins,
下一次 `hub sync` 的 `git add -A` 把它记成 mode 160000。本机看着一切正常,
`hub status --check` 全 [ok] 退 0(它的插件判据读的是**盘上那个嵌套仓**),
但父仓记下的是一个它自己都没有的 commit sha —— 别的设备 clone 下来是空目录。
更糟的是没有出路:`git add` 对 gitlink 是 no-op,migrate-plugins 见到 gitlink 直接拒绝。
"""
import subprocess
from pathlib import Path

import pytest

from hub.backend import GitBackend, GitlinkTracked, ConflictError, RemoteUnavailable, tracked_gitlinks
from hub.cli import main


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")


def _init_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "seed.txt").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "seed")


def _vault_with_nested_plugin(tmp_path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    _init_repo(vault)
    plug = vault / "shared" / "plugins" / "foo"
    plug.mkdir(parents=True)
    (plug / "SKILL.md").write_text("hi\n", encoding="utf-8")
    _init_repo(plug)                       # 嵌套独立仓:插件的正常形态
    return vault, plug


def test_publish_refuses_to_commit_a_gitlink(tmp_path):
    vault, _ = _vault_with_nested_plugin(tmp_path)
    b = GitBackend(vault)
    with pytest.raises(GitlinkTracked) as ei:
        b.publish("chore(hub): sync")
    assert "shared/plugins/foo" in str(ei.value)
    assert "hub induct" in str(ei.value), "报错必须给出路,否则用户卡死在这"
    head = subprocess.run(["git", "log", "--oneline"], cwd=str(vault), capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout
    assert head.count("\n") == 1, "闸必须挡在 commit 之前,不是之后"


def test_induct_rescues_an_already_committed_gitlink(tmp_path, capsys):
    vault, plug = _vault_with_nested_plugin(tmp_path)
    _git(vault, "add", "-A")               # 事故现场:gitlink 已经被提交进历史
    _git(vault, "commit", "-qm", "oops")
    assert tracked_gitlinks(vault) == ["shared/plugins/foo"]

    rc = main(["induct", "--vault", str(vault), "shared/plugins/foo"])
    assert rc == 0
    assert tracked_gitlinks(vault) == []
    tracked = subprocess.run(["git", "ls-files", "shared/plugins/foo"], cwd=str(vault),
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace").stdout.split()
    assert "shared/plugins/foo/SKILL.md" in tracked, "内容必须真进父仓,不是又一个空壳"
    assert not any("/.git/" in t for t in tracked), "嵌套 .git 不许进父仓"
    assert (plug / ".git").exists(), "嵌套仓自己必须原样还在盘上"

    GitBackend(vault).publish("chore(hub): sync")     # 修完之后闸不再拦
    assert tracked_gitlinks(vault) == []


def test_induct_rejects_a_path_outside_the_vault(tmp_path):
    vault, _ = _vault_with_nested_plugin(tmp_path)
    assert main(["induct", "--vault", str(vault), "../escape"]) == 1


def test_remote_unavailable_is_not_sold_as_a_conflict(tmp_path):
    """pull 够不着远端 ≠ 内容冲突。文案把人指去手工解冲突,是纯粹的浪费。"""
    vault = tmp_path / "vault"
    _init_repo(vault)
    _git(vault, "remote", "add", "origin", str(tmp_path / "nowhere"))
    with pytest.raises(RemoteUnavailable):
        GitBackend(vault).acquire()
    assert issubclass(RemoteUnavailable, ConflictError)   # 老的 except 分支不受影响
