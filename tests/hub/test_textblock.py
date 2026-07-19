import pytest
from hub.textblock import upsert_block, BlockError, BEGIN, END

def test_append_when_absent():
    out = upsert_block("user stuff\n", "HELLO")
    assert "user stuff" in out and BEGIN in out and END in out and "HELLO" in out

def test_replace_inside_preserves_outside():
    src = f"top\n{BEGIN}\nold\n{END}\nbottom\n"
    out = upsert_block(src, "NEW")
    assert "top" in out and "bottom" in out and "NEW" in out and "old" not in out

def test_idempotent():
    once = upsert_block("x\n", "B")
    assert upsert_block(once, "B") == once

def test_duplicate_markers_raise():
    src = f"{BEGIN}\na\n{END}\n{BEGIN}\nb\n{END}\n"
    with pytest.raises(BlockError):
        upsert_block(src, "N")

def test_missing_end_raises():
    with pytest.raises(BlockError):
        upsert_block(f"{BEGIN}\nno end\n", "N")

def test_reversed_markers_raise():
    with pytest.raises(BlockError):
        upsert_block(f"{END}\nx\n{BEGIN}\n", "N")

def test_has_one_valid_block():
    from hub.textblock import has_one_valid_block
    assert has_one_valid_block(f"{BEGIN}\nx\n{END}\n") is True
    assert has_one_valid_block("no markers") is False
    assert has_one_valid_block(f"{BEGIN}\nno end\n") is False           # 缺半边
    assert has_one_valid_block(f"{BEGIN}\na\n{END}\n{BEGIN}\nb\n{END}") is False  # 重复
    assert has_one_valid_block(f"{END}\nx\n{BEGIN}\n") is False         # 颠倒
