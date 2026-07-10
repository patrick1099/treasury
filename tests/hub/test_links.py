from hub.links import lint_raw_paths, resolve_symbols

def test_lint_flags_windows_and_posix_abspath():
    assert lint_raw_paths("见 C:\\Users\\huawei\\x.md 里") != []
    assert lint_raw_paths("见 /home/u/x.md") != []
    assert lint_raw_paths("见 $VAULT/x.md 和 [[slug]]") == []

def test_lint_does_not_flag_urls():
    assert lint_raw_paths("查看 http://example.com/docs/x.md 页面") == []
    assert lint_raw_paths("见 https://github.com/foo/bar 仓库") == []

def test_resolve_symbols_expands_defined_roots():
    out, missing = resolve_symbols("看 $SECRETS/INDEX.md", {"SECRETS": "C:/s"})
    assert out == "看 C:/s/INDEX.md"
    assert missing == []

def test_resolve_reports_missing_roots():
    out, missing = resolve_symbols("看 $VAULT/a 与 $NOPE/b", {"VAULT": "Z:/v"})
    assert "Z:/v/a" in out
    assert missing == ["NOPE"]
