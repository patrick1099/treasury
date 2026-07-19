import pytest
from hub.hubconfig import write_config, read_config, ConfigConflict, hub_config_path
from hub.writer import Writer

def test_write_and_read(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    write_config(tmp_path / "vault", "box", tmp_path / "repo", Writer())
    cfg = read_config()
    assert cfg["host"] == "box" and cfg["vault"].endswith("vault")

def test_conflict_on_different_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    write_config(tmp_path / "v1", "box", tmp_path / "repo", Writer())
    with pytest.raises(ConfigConflict):
        write_config(tmp_path / "v2", "box", tmp_path / "repo", Writer())
