from hub.managed_block import replace_block, extract_block, BEGIN, END

def test_append_when_absent():
    out = replace_block("用户手写内容\n", "生成A")
    assert "用户手写内容" in out
    assert BEGIN in out and END in out
    assert extract_block(out) == "生成A"

def test_replace_is_idempotent_and_preserves_outside():
    once = replace_block("头部\n", "V1")
    twice = replace_block(once, "V2")
    assert "头部" in twice
    assert extract_block(twice) == "V2"
    assert twice.count(BEGIN) == 1 and twice.count(END) == 1

def test_extract_none_when_no_block():
    assert extract_block("纯手写\n") is None
