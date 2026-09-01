from hub.schema_md import SCHEMA_MD


def test_schema_v3_contract():
    assert "version = 3" in SCHEMA_MD
    assert "shared/plugins/manifest.toml" in SCHEMA_MD
    assert "induction" in SCHEMA_MD.lower()
    assert "嵌套" in SCHEMA_MD and ".git" in SCHEMA_MD


def test_schema_lifecycle_fields_contract():
    """group / archived / index 已影响视图行为,契约文本必须说清楚——否则文档在撒谎
    (docs/plans/2026-08-31-hub-memory-layering.md §4 连带)。"""
    assert "group" in SCHEMA_MD
    assert "archived" in SCHEMA_MD
    assert "index" in SCHEMA_MD
    assert "10 个字段" in SCHEMA_MD
    assert "生命周期" in SCHEMA_MD
    assert "归档 ≠ 删除" in SCHEMA_MD
