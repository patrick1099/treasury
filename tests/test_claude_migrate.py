import sys
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

import claude_migrate  # noqa: E402


# ---------------------------------------------------------------- 路径编码

def test_encode_project_path_matches_claude_scheme():
    enc = claude_migrate.encode_project_path
    # 与本机真实目录名逐一核对过的样例
    assert enc(r"C:\Users\dell") == "C--Users-dell"
    assert enc(r"C:\Users\dell\Desktop\Mine\rt-thread-5.2.2") == \
        "C--Users-dell-Desktop-Mine-rt-thread-5-2-2"
    # 中文段:每个字符各占一个 '-',不折叠
    assert enc("C:\\Users\\dell\\Desktop\\需求\\新奥集团商超开发\\Code") == \
        "C--Users-dell-Desktop-------------Code"
    # 字面 '-' 原样保留(也是非字母数字->'-')
    assert enc(r"C:\a\remaining-qa") == "C--a-remaining-qa"


# ---------------------------------------------------------------- 路径搬迁

def _seed_project(projects_dir, enc_name, cwd):
    """造一个会话目录:一条带 cwd 的 jsonl + 一份 memory 文件。"""
    d = projects_dir / enc_name
    (d / "memory").mkdir(parents=True)
    # jsonl 里 cwd 用 JSON 转义(双反斜杠);memory 里用单反斜杠
    (d / "s.jsonl").write_text(
        '{"cwd":"' + cwd.replace("\\", "\\\\") + '","msg":"hi"}\n',
        encoding="utf-8",
    )
    (d / "memory" / "note.md").write_text(f"工程在 {cwd} 下\n", encoding="utf-8")
    return d


def test_remap_path_renames_dir_and_rewrites_content(tmp_path):
    projects = tmp_path / "projects"
    old = r"C:\Users\dell\Desktop\proj"
    new = r"D:\work\xinao"
    enc_old = claude_migrate.encode_project_path(old)
    enc_new = claude_migrate.encode_project_path(new)
    _seed_project(projects, enc_old, old)

    renamed, rewritten = claude_migrate.remap_path_projects(projects, old, new)

    assert renamed == 1
    assert rewritten == 2  # jsonl + note.md
    assert not (projects / enc_old).exists()
    new_dir = projects / enc_new
    assert new_dir.exists()
    # 内容里旧路径已全部换成新路径(两种写法都换到)
    jsonl = (new_dir / "s.jsonl").read_text(encoding="utf-8")
    assert new.replace("\\", "\\\\") in jsonl
    assert "dell" not in jsonl
    note = (new_dir / "memory" / "note.md").read_text(encoding="utf-8")
    assert new in note and old not in note


def test_remap_path_also_moves_worktree_subdirs(tmp_path):
    projects = tmp_path / "projects"
    old = r"C:\Users\dell\Desktop\proj"
    new = r"D:\work\xinao"
    enc_old = claude_migrate.encode_project_path(old)
    enc_new = claude_migrate.encode_project_path(new)
    # 主目录 + 一个 worktree 子目录(编码后是 enc_old + '--worktree-x')
    _seed_project(projects, enc_old, old)
    _seed_project(projects, enc_old + "--worktree-x", old + r"\.worktree\x")
    # 一个无关项目,不应被动到
    _seed_project(projects, "C--Users-dell-other", r"C:\Users\dell\other")

    renamed, _ = claude_migrate.remap_path_projects(projects, old, new)

    assert renamed == 2
    assert (projects / enc_new).exists()
    assert (projects / (enc_new + "--worktree-x")).exists()
    assert (projects / "C--Users-dell-other").exists()  # 没误伤


def test_remap_path_merges_into_existing_target(tmp_path):
    projects = tmp_path / "projects"
    old = r"C:\Users\dell\Desktop\proj"
    new = r"D:\work\xinao"
    enc_old = claude_migrate.encode_project_path(old)
    enc_new = claude_migrate.encode_project_path(new)
    _seed_project(projects, enc_old, old)
    # 目标已存在(新机已有同名项目历史)
    (projects / enc_new).mkdir(parents=True)
    (projects / enc_new / "existing.jsonl").write_text("{}\n", encoding="utf-8")

    renamed, _ = claude_migrate.remap_path_projects(projects, old, new)

    assert renamed == 1
    assert not (projects / enc_old).exists()
    assert (projects / enc_new / "existing.jsonl").exists()  # 旧内容保留
    assert (projects / enc_new / "s.jsonl").exists()         # 新内容并入


def test_remap_path_noop_when_no_match(tmp_path):
    projects = tmp_path / "projects"
    _seed_project(projects, "C--Users-dell-unrelated", r"C:\Users\dell\unrelated")
    renamed, rewritten = claude_migrate.remap_path_projects(
        projects, r"C:\nope\here", r"D:\else\where"
    )
    assert (renamed, rewritten) == (0, 0)
