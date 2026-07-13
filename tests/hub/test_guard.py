import pytest
from pathlib import Path
from hub.guard import check_source, is_denied, SecretPathError


def test_secrets_dir_is_denied():
    assert is_denied(Path("C:/Users/x/.claude/secrets"))
    assert is_denied(Path("C:/Users/x/.claude/secrets/oss.md"))   # 目录下的任何文件


def test_auth_json_is_denied():
    assert is_denied(Path("C:/Users/x/.codex/auth.json"))


def test_dotenv_is_denied():
    assert is_denied(Path("C:/proj/.env"))


def test_normal_paths_pass():
    assert not is_denied(Path("C:/Users/x/.claude/skills"))
    assert not is_denied(Path("C:/Users/x/.claude/projects/p/memory"))


def test_check_source_raises_with_the_path_named():
    with pytest.raises(SecretPathError, match="secrets"):
        check_source(Path("C:/Users/x/.claude/secrets"))


def test_check_source_is_silent_on_normal_paths():
    check_source(Path("C:/Users/x/.claude/skills"))     # 不抛就是通过


def test_case_insensitive():
    assert is_denied(Path("C:/Users/x/.claude/Secrets/a.md"))


def test_no_false_positive_on_similar_name():
    # 组件级匹配：文件名恰好"包含" secrets 子串不该被拒
    assert not is_denied(Path("C:/Users/x/docs/secretsanta.md"))
    assert not is_denied(Path("C:/Users/x/docs/my-secrets-notes.md"))


def test_relative_path_component_still_denied():
    assert is_denied(Path("secrets/oss.md"))
    assert is_denied(Path("./secrets/oss.md"))
