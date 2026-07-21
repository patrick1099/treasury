from hub.schema_md import SCHEMA_MD

def test_schema_v3_contract():
    assert "version = 3" in SCHEMA_MD
    assert "shared/plugins/manifest.toml" in SCHEMA_MD
    assert "induction" in SCHEMA_MD.lower()
    assert "嵌套" in SCHEMA_MD and ".git" in SCHEMA_MD
