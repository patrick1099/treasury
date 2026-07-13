import tomllib
from hub.tomlout import dump_toml

def test_roundtrips_through_tomllib():
    out = dump_toml([
        ("claude.repos.cjt", {"remote": "https://github.com/x/cjt.git",
                              "sha": "abc123", "dirty": False}),
        ("claude.enabled", {"superpowers@claude-plugins-official": True,
                            "compact-plus@xu-local": False}),
    ])
    back = tomllib.loads(out)
    assert back["claude"]["repos"]["cjt"]["dirty"] is False
    assert back["claude"]["enabled"]["superpowers@claude-plugins-official"] is True
    assert back["claude"]["enabled"]["compact-plus@xu-local"] is False

def test_keys_needing_quotes_are_quoted():
    out = dump_toml([("t", {"a@b": True})])
    assert '"a@b" = true' in out
    assert tomllib.loads(out)["t"]["a@b"] is True

def test_windows_paths_are_escaped():
    out = dump_toml([("t", {"path": "C:\\Users\\x\\.claude"})])
    assert tomllib.loads(out)["t"]["path"] == "C:\\Users\\x\\.claude"

def test_empty_table_still_emits_header():
    assert "[t]" in dump_toml([("t", {})])
