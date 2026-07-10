from hub.derive import render_memory_index
from hub.model import Memory

def _m(name, desc):
    return Memory(name=name, description=desc, type="project",
                  scope=["global"], portable=True, sensitive=False, body="b")

def test_index_sorted_and_formatted():
    out = render_memory_index([_m("zeta", "最后"), _m("alpha", "最先")])
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    assert lines[0] == "- [alpha](alpha.md) — 最先"
    assert lines[1] == "- [zeta](zeta.md) — 最后"
    assert "自动生成" in out  # 派生物声明
