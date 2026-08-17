"""原始对话库不进 git 的双保险：.gitignore 幂等写入 + 提交路径上的代码闸。

真机事故的失败方向(不可撤销):对话正文必然含明文密钥和公司源码,而 git 的每个
历史版本永久留存。只靠 .gitignore 不够——它哪天被改坏、或某个文件早被 git add -f
强行加进索引,下一次 hub sync 的 git add -A 就会把 800 MB 明文对话静默推上
GitHub。所以闸必须设在提交路径上(提交之前),发现任何 */chats/* 的已跟踪路径就
抛 ChatsTracked,一个字节都不提交。
"""
import subprocess
from pathlib import Path

import pytest

from hub.backend import GitBackend, ChatsTracked, GitlinkTracked
from hub.chats.gitignore import ensure_chats_ignored
from hub.writer import Writer


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


def _tracked(repo) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=str(repo), capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout
    return out.splitlines()


def test_publish_refuses_to_commit_a_tracked_chats_file(tmp_path):
    """git add -f 过的 chats 文件走后门进了索引,提交路径必须拦住、零提交。"""
    vault = tmp_path / "vault"
    _init_repo(vault)
    chats = vault / "win" / "claude" / "chats" / "sessions" / "s1.jsonl"
    chats.parent.mkdir(parents=True)
    chats.write_text("secret cleartext\n", encoding="utf-8")
    _git(vault, "add", "-f", "win/claude/chats/sessions/s1.jsonl")
    assert "win/claude/chats/sessions/s1.jsonl" in _tracked(vault)

    with pytest.raises(ChatsTracked) as ei:
        GitBackend(vault).publish("chore(hub): sync")
    assert "win/claude/chats/sessions/s1.jsonl" in str(ei.value)
    assert "git rm --cached -r" in str(ei.value), "报错必须给出路,否则人卡死在这"

    head = subprocess.run(["git", "log", "--oneline"], cwd=str(vault), capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout
    assert head.count("\n") == 1, "闸必须挡在 commit 之前,不是之后"


def test_rm_cached_rescues_and_publish_then_succeeds(tmp_path):
    """git rm --cached 解除跟踪后,同一个仓照常提交(闸别把仓锁死)。"""
    vault = tmp_path / "vault"
    _init_repo(vault)
    chats = vault / "win" / "codex" / "chats" / "sessions" / "x.jsonl"
    chats.parent.mkdir(parents=True)
    chats.write_text("ms\n", encoding="utf-8")
    _git(vault, "add", "-f", "win/codex/chats/sessions/x.jsonl")
    with pytest.raises(ChatsTracked):
        GitBackend(vault).publish("oops")
    _git(vault, "rm", "-q", "--cached", "-r", "win/codex/chats/sessions/x.jsonl")
    # 解除跟踪后还得有 .gitignore 兜着,否则 publish 的 `git add -A` 立刻把它加回来
    # —— 这正是两道保险各管一段:.gitignore 拦住日常,代码闸拦住 .gitignore 失效时。
    ensure_chats_ignored(vault, Writer())
    GitBackend(vault).publish("chore(hub): sync")
    assert "win/codex/chats/sessions/x.jsonl" not in _tracked(vault)
    assert chats.exists(), "解除跟踪不等于删文件,证据必须还在盘上"


def test_normal_paths_are_not_blocked(tmp_path):
    """shared/ 和 <host>/claude/memory 下的文件照常提交,不误伤。"""
    vault = tmp_path / "vault"
    _init_repo(vault)
    cases = [
        "shared/plugins/foo/SKILL.md",
        "win/claude/memory/notes.md",
        "win/claude/memory/chats_are_not_here.md",
    ]
    for rel in cases:
        f = vault / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("ok\n", encoding="utf-8")
        _git(vault, "add", rel)
    GitBackend(vault).publish("chore(hub): sync")
    # 提交成功,且这几个文件确实进了历史
    head = subprocess.run(["git", "log", "--oneline"], cwd=str(vault), capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout
    assert head.count("\n") == 2, "seed + sync 两笔提交"
    for rel in cases:
        assert rel in _tracked(vault)


def test_gitignore_idempotent_writes_once(tmp_path):
    """连跑两次 ensure_chats_ignored,第二次零写入。"""
    vault = tmp_path / "vault"
    _init_repo(vault)
    gitignore = vault / ".gitignore"

    w1 = Writer()
    assert ensure_chats_ignored(vault, w1) is True
    assert gitignore in w1.written
    first = gitignore.read_text(encoding="utf-8")
    assert "*/*/chats/" in first
    assert "原始对话库" in first

    w2 = Writer()
    assert ensure_chats_ignored(vault, w2) is False
    assert w2.written == [], "幂等:第二次一个字节都不写"
    assert gitignore.read_text(encoding="utf-8") == first


def test_gitignore_preserves_existing_content(tmp_path):
    """金库根已有别的 .gitignore 内容时,只追加、不覆盖人家的。"""
    vault = tmp_path / "vault"
    _init_repo(vault)
    gitignore = vault / ".gitignore"
    gitignore.write_text("build/out/\n", encoding="utf-8")

    w = Writer()
    ensure_chats_ignored(vault, w)
    text = gitignore.read_text(encoding="utf-8")
    assert "build/out/" in text, "既有内容必须保留"
    assert "*/*/chats/" in text
    assert text.index("build/out/") < text.index("*/*/chats/")


def test_gitignore_dry_run_writes_nothing(tmp_path):
    """dry-run 下零写入,但报告会照常判定需要写。"""
    vault = tmp_path / "vault"
    _init_repo(vault)
    gitignore = vault / ".gitignore"

    w = Writer(dry_run=True)
    assert ensure_chats_ignored(vault, w) is True
    assert not gitignore.exists(), "dry-run 不落盘"