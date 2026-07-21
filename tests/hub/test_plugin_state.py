from hub.writer import Writer
from hub.plugin_state import read_state, record
def test_per_plugin_per_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    record("cjt","claude","aaa","0.1.0", Writer())
    record("cjt","codex","bbb","0.1.0", Writer())
    st = read_state()
    assert st["cjt"]["claude"].sha=="aaa" and st["cjt"]["codex"].sha=="bbb"
    record("cjt","claude","ccc","0.2.0", Writer())
    st = read_state()
    assert st["cjt"]["claude"].version=="0.2.0" and st["cjt"]["codex"].sha=="bbb"  # codex 不动
def test_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    assert read_state() == {}
