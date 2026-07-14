import pytest
from pathlib import Path
from hub.guard import (check_source, is_denied, has_denied_component,
                       read_source_text, SecretPathError)


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


def test_dotdot_traversal_with_secrets_component_is_denied():
    # 字面 parts 里就带 secrets,不需要 resolve 也该拒绝
    assert is_denied(Path("C:/Users/x/other/../secrets/oss.md"))


def test_is_denied_accepts_str():
    assert is_denied("C:/Users/x/.claude/secrets/oss.md")
    assert not is_denied("C:/Users/x/.claude/skills")


def test_resolution_failure_is_denied_fail_closed(monkeypatch):
    """resolve() 抛 OSError(如符号链接环)时,不确定就当作拒绝——闸门失效应该
    向着"拒绝读取"的方向失效,而不是放行。"""

    def boom(self, strict=False):
        raise OSError("simulated resolution failure (e.g. symlink loop)")

    monkeypatch.setattr(Path, "resolve", boom)
    assert is_denied(Path("C:/Users/x/.claude/skills/foo.md"))


def test_bare_relative_filename_with_cwd_inside_secrets_is_denied(tmp_path, monkeypatch):
    """非符号链接版本,验证同一条底层性质:字面路径没有 secrets 分量(裸文件名),
    但 cwd 已经在真实的 secrets/ 目录下,resolve() 后应命中。任何机器都能跑。"""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.chdir(secrets_dir)
    assert is_denied(Path("oss.md"))


def test_symlink_into_secrets_dir_is_denied(tmp_path):
    """符号链接绕闸:tmp_path/link -> tmp_path/secrets,通过 link 呈现的路径字面上
    不含 secrets 分量,但真实指向 secrets/ 内部,resolve() 后必须命中。

    Windows 上创建符号链接需要开发者模式或管理员权限;若本机没有该权限,
    创建会抛 OSError/PermissionError —— 此时跳过并写明原因,不要用 mock 顶替,
    以免误报"已验证"。
    """
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "oss.md").write_text("token=super-secret", encoding="utf-8")

    link = tmp_path / "not_secrets_by_name"
    try:
        link.symlink_to(secrets_dir, target_is_directory=True)
    except OSError as e:
        pytest.skip(f"无法在本机创建符号链接(权限/开发者模式受限): {e}")

    linked_path = link / "oss.md"
    assert is_denied(linked_path)


def test_has_denied_component_matches_literal_parts():
    assert has_denied_component(Path("secrets/token.md"))
    assert has_denied_component(Path("a/.env"))
    assert not has_denied_component(Path("a/secretsanta.md"))


def test_has_denied_component_does_not_resolve_or_touch_cwd(tmp_path, monkeypatch):
    """这是 has_denied_component 存在的理由:tar 归档成员名是归档内部的相对路径,
    不是文件系统路径。cwd 恰好在真实的 secrets/ 目录下时,一个字面上不含
    secrets 分量的裸相对名(如 "oss.md")不该被这个纯字面版本判定为拒绝——
    如果它去 resolve(),就会像 is_denied() 那样因 cwd 而被误判,导致挡出去的
    tar 成员筛选依附于进程当前目录这种偶然状态。"""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    monkeypatch.chdir(secrets_dir)
    assert not has_denied_component(Path("oss.md"))
    assert is_denied(Path("oss.md"))          # 对照:is_denied 的 resolve 半部分确实命中


# ---- 带硬闸的读原语(最终评审 finding 6) ----------------------------------

def test_read_source_text_reads_normal_file(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    assert read_source_text(p) == '{"a": 1}'

def test_read_source_text_refuses_denied_path(tmp_path):
    """`check_source(x)` 然后 `x.read_text()` 这个惯用法散落在 decl.py 里两处,
    忘掉前半句就直接把密钥读进下游。读原语把闸焊在里面 —— 直接调它,证明它自己会拒。"""
    p = tmp_path / "secrets" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text("token=super-secret", encoding="utf-8")
    with pytest.raises(SecretPathError):
        read_source_text(p)
