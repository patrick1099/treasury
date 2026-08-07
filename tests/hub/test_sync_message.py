"""`hub sync -m` 的提交说明。

金库大部分内容是派生/快照（记忆、索引、视图），固定串 "chore(hub): sync" 反而诚实；
但 manifest.toml / <设备>/device.toml 这类是**有意图的配置**，改动理由有价值。这组测试
钉住两件事：缺省行为一字不变（既有 sync 历史全靠它），以及**永远不会造出空标题的提交**。
"""
import subprocess
from types import SimpleNamespace
from pathlib import Path
from hub.cli import main, sync_message, DEFAULT_SYNC_MESSAGE
from tests.hub.test_cli import _init_git, _mk_vault

def _subjects(repo: Path) -> list[str]:
    r = subprocess.run(["git", "log", "--format=%s"], cwd=repo, check=True,
                       capture_output=True, text=True, encoding="utf-8")
    return r.stdout.splitlines()

# ── 纯函数：消息选取 ───────────────────────────────────────────────────
def test_default_when_flag_absent():
    assert sync_message(SimpleNamespace()) == DEFAULT_SYNC_MESSAGE
    assert sync_message(SimpleNamespace(message=None)) == DEFAULT_SYNC_MESSAGE

def test_custom_message_is_used_and_stripped():
    assert sync_message(SimpleNamespace(message="  feat: 有意图的改动  ")) == "feat: 有意图的改动"

def test_blank_message_falls_back_never_empty():
    """空串/全空白一律回落缺省——git commit -m '' 会造出没有标题的提交，log 里就是一行
    空白，事后谁都看不懂。宁可用固定串。"""
    for blank in ("", "   ", "\t", "\n  \n"):
        assert sync_message(SimpleNamespace(message=blank)) == DEFAULT_SYNC_MESSAGE

def test_multiline_message_keeps_body():
    msg = "feat(plugins): 标题\n\n正文解释为什么这么改。"
    assert sync_message(SimpleNamespace(message=msg)) == msg

# ── 端到端：真的落进 git 历史 ──────────────────────────────────────────
def test_sync_without_message_uses_default_subject(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    assert main(["sync", "--vault", str(vault), "--host", "h1"]) == 0
    assert _subjects(vault)[0] == DEFAULT_SYNC_MESSAGE

def test_sync_with_message_lands_in_history(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    assert main(["sync", "--vault", str(vault), "--host", "h1",
                 "-m", "feat(plugins): opencode 列为一等平台"]) == 0
    assert _subjects(vault)[0] == "feat(plugins): opencode 列为一等平台"

def test_long_flag_form_works(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    assert main(["sync", "--vault", str(vault), "--host", "h1",
                 "--message", "docs: 说明"]) == 0
    assert _subjects(vault)[0] == "docs: 说明"

def test_blank_message_end_to_end_never_produces_empty_subject(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    assert main(["sync", "--vault", str(vault), "--host", "h1", "-m", "   "]) == 0
    assert _subjects(vault)[0] == DEFAULT_SYNC_MESSAGE
