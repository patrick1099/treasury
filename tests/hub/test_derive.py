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

def test_index_sorted_by_origin_then_name(tmp_path):
    """Verify memories are sorted by (origin or "", name).

    Input order is intentionally scrambled to ensure sort is actually happening.
    If sorted() were removed from render_memory_index, this test would fail.
    """
    # Insertion order: zeta(device_z), beta(device_a), gamma(shared), alpha(shared)
    # This is NOT in sorted order by (origin or "", name)
    ms = [_m("zeta", "device_z", tmp_path / "device_z" / "claude" / "memory" / "zeta.md"),
          _m("beta", "device_a", tmp_path / "device_a" / "claude" / "memory" / "beta.md"),
          _m("gamma", SHARED, tmp_path / "shared" / "memory" / "gamma.md"),
          _m("alpha", SHARED, tmp_path / "shared" / "memory" / "alpha.md")]

    out = render_memory_index(ms, tmp_path)
    lines = [l for l in out.splitlines() if l.startswith("- [")]

    # Expected sorted order by (origin or "", name):
    # ("device_a", "beta"), ("device_z", "zeta"), ("shared", "alpha"), ("shared", "gamma")
    assert lines[0] == "- [beta](device_a/claude/memory/beta.md) — beta 摘要"
    assert lines[1] == "- [zeta](device_z/claude/memory/zeta.md) — zeta 摘要"
    assert lines[2] == "- [alpha](shared/memory/alpha.md) — alpha 摘要"
    assert lines[3] == "- [gamma](shared/memory/gamma.md) — gamma 摘要"
