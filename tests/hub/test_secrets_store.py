import pytest
from hub.secrets_store import SecretsError, item_path, parse_fields, load_item, iter_items

DOC = """---
name: demo
description: d
metadata:
  type: secret
---

## fields

accessKeyId = LTAIxxxxxxxxxxxx
accessKeySecret = aB3-dE_f.gH

## notes

下游副本：~/.mineru/config.yaml
accessKeyId = 这一行在 notes 段里，不许被解析出来
"""

def _mk(root, name, text=DOC):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(text, encoding="utf-8")

def test_fields_section_only(tmp_path):
    assert parse_fields(DOC) == {
        "accessKeyId": "LTAIxxxxxxxxxxxx",
        "accessKeySecret": "aB3-dE_f.gH",
    }                                    # notes 段里那行不许混进来

def test_value_kept_verbatim(tmp_path):
    jwt = "a." + "x" * 380 + "-_"        # 402 位量级，含 . - _
    text = DOC.replace("LTAIxxxxxxxxxxxx", jwt)
    assert parse_fields(text)["accessKeyId"] == jwt   # 不剥引号、不 strip 内部、不转义

def test_duplicate_key_refused(tmp_path):
    text = DOC.replace("accessKeySecret = aB3-dE_f.gH", "accessKeyId = second")
    with pytest.raises(SecretsError):
        parse_fields(text)

def test_missing_fields_section_refused(tmp_path):
    with pytest.raises(SecretsError):
        parse_fields("---\nname: x\n---\n\n## notes\n\nnothing\n")

@pytest.mark.parametrize("bad", [
    "..", ".", "a/b", "a\\b", "/abs", "C:/abs", ".hidden", "", "a\x00b",
])
def test_item_name_strictly_refused(tmp_path, bad):
    with pytest.raises(SecretsError):
        item_path(tmp_path, bad)

def test_item_must_be_regular_file(tmp_path):
    (tmp_path / "adir.md").mkdir()
    with pytest.raises(SecretsError):
        item_path(tmp_path, "adir")

def test_load_item_ok(tmp_path):
    _mk(tmp_path, "demo")
    assert load_item(tmp_path, "demo")["accessKeyId"] == "LTAIxxxxxxxxxxxx"

def test_iter_items_excludes_dotfiles(tmp_path):
    _mk(tmp_path, "demo")
    (tmp_path / ".unlock").write_text("whatever", encoding="utf-8")
    (tmp_path / "INDEX.md").write_text("# idx\n", encoding="utf-8")
    assert iter_items(tmp_path) == ["INDEX", "demo"]   # .unlock 绝不是一条密钥