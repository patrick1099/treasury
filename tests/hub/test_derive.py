from pathlib import Path
from hub.derive import render_memory_index
from hub.model import Memory, SHARED

def _m(name, origin, path):
    return Memory(name=name, description=f"{name} 摘要", type="reference",
                  scope=["global"], portable=True, sensitive=False,
                  body="正文\n", path=path, origin=origin)

def test_index_links_point_at_real_paths(tmp_path):
    ms = [_m("s1", SHARED, tmp_path / "shared" / "memory" / "s1.md"),
          _m("m1", "box1", tmp_path / "box1" / "claude" / "memory" / "m1.md")]
    out = render_memory_index(ms, tmp_path)
    assert "[s1](shared/memory/s1.md)" in out
    assert "[m1](box1/claude/memory/m1.md)" in out
    assert "s1 摘要" in out and "m1 摘要" in out
