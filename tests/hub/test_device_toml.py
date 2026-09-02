from pathlib import Path
from hub.device_toml import update_device_toml
from hub.writer import Writer


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_update_plugin_and_skill_preserves_other_fields_and_comments(tmp_path):
    p = tmp_path / "device.toml"
    _write(p, """# device config
class = ["work"]
projects = []
[paths]
VAULT = "x"

[plugins.claude]
# keep this comment
enabled = ["a", "b"]  # trailing
[plugins.codex]
enabled = ["c"]
[skills.opencode]
enabled = ["s1"]
""")
    changed = update_device_toml(
        p,
        plugins={"claude": ["a", "b", "cjt"]},
        skills={"opencode": ["s2"]},
    )
    assert changed is True
    text = p.read_text(encoding="utf-8")
    assert "# device config" in text
    assert "# keep this comment" in text
    assert 'VAULT = "x"' in text
    assert 'enabled = ["a", "b", "cjt"]' in text
    assert "[plugins.codex]" in text
    assert 'enabled = ["c"]' in text
    assert 'enabled = ["s2"]' in text


def test_update_adds_missing_section_and_enabled_line(tmp_path):
    p = tmp_path / "device.toml"
    _write(p, """class=[]
projects=[]
[paths]
VAULT="x"
""")
    changed = update_device_toml(
        p,
        plugins={"dsh": ["cjt"]},
        skills={"dsh": ["alpha"]},
    )
    assert changed is True
    text = p.read_text(encoding="utf-8")
    assert "[plugins.dsh]" in text and 'enabled = ["cjt"]' in text
    assert "[skills.dsh]" in text and 'enabled = ["alpha"]' in text
    assert "class=[]" in text


def test_update_no_change_is_zero_write(tmp_path):
    p = tmp_path / "device.toml"
    _write(p, """[plugins.claude]
enabled=["a"]
""")
    w = Writer()
    changed = update_device_toml(p, plugins={"claude": ["a"]}, w=w)
    assert changed is False
    assert w.written == []


def test_dry_run_does_not_modify_file(tmp_path):
    p = tmp_path / "device.toml"
    original = """[plugins.claude]
enabled=["a"]
"""
    _write(p, original)
    w = Writer(dry_run=True)
    changed = update_device_toml(p, plugins={"claude": ["a", "b"]}, w=w)
    assert changed is True
    assert p.read_text(encoding="utf-8") == original
    assert len(w.written) == 1
