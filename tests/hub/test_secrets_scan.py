from pathlib import Path

from hub.secrets_scan import scan_text, scan_tree


def test_catches_known_prefixes():
    hits = scan_text("key = sk-abc123def456ghi789jkl\n", Path("a.md"))
    assert len(hits) == 1 and hits[0].kind == "openai"


def test_catches_aliyun_and_github():
    assert scan_text("LTAI5tSomethingLong123\n", Path("a"))[0].kind == "aliyun"
    assert scan_text("ghp_abcdefghijklmnopqrstuvwxyz0123\n", Path("a"))[0].kind == "github"


def test_does_not_fire_on_task_dash():
    # 真实误报：`sk-` 撞上 `task-fix3-report`。这是本模块只提醒不阻断的理由。
    assert scan_text("# task-fix3-report:收口\n", Path("a.md")) == []


def test_does_not_fire_on_prose():
    assert scan_text("把 token 存进 secrets 目录,记忆里只留指针\n", Path("a.md")) == []


def test_reports_line_number_and_redacts_sample():
    hits = scan_text("行一\n行二\nghp_abcdefghijklmnopqrstuvwxyz0123\n", Path("a.md"))
    assert hits[0].line == 3
    assert "…" in hits[0].sample                 # 只给前缀，不把明文抄进 transcript
    assert "wxyz0123" not in hits[0].sample


def test_scan_tree_skips_binaries(tmp_path):
    (tmp_path / "a.md").write_text("ghp_abcdefghijklmnopqrstuvwxyz0123\n", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01ghp_abcdefghijklmnopqrstuvwxyz0123")
    hits = scan_tree(tmp_path)
    assert [h.path.name for h in hits] == ["a.md"]
