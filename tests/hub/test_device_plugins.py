from hub.vault import load_device


def test_device_plugins(tmp_path):
    (tmp_path/"box").mkdir()
    (tmp_path/"box"/"device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'
        '[plugins.claude]\nenabled=["cjt","xu-skills"]\n[plugins.codex]\nenabled=["cjt"]\n',
        encoding="utf-8")
    dev = load_device(tmp_path, "box")
    assert dev.plugins == {"claude":["cjt","xu-skills"], "codex":["cjt"]}

def test_device_no_plugins_section(tmp_path):
    (tmp_path/"box").mkdir()
    (tmp_path/"box"/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n', encoding="utf-8")
    assert load_device(tmp_path, "box").plugins == {}

def test_device_parses_skills_section(tmp_path):
    (tmp_path/"box").mkdir()
    (tmp_path/"box"/"device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'
        '[skills.opencode]\nenabled=["alpha"]\n'
        '[skills.dsh]\nenabled=["beta"]\n',
        encoding="utf-8")
    dev = load_device(tmp_path, "box")
    assert dev.skills == {"opencode": ["alpha"], "dsh": ["beta"]}

