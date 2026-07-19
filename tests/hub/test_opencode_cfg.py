import json
from pathlib import Path
import pytest
from hub.writer import Writer
from hub.model import DeviceProfile
from hub.opencode_cfg import plan_instruction, commit_instruction

def _dev(cfg): return DeviceProfile(host="b", classes=[], projects=[],
                                    paths={"OPENCODE_CONFIG": str(cfg)}, sources={})

def test_adds_to_existing_array(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"model": "x", "instructions": ["a.md"]}), encoding="utf-8")
    view = tmp_path / "v" / "MEMORY.md"
    plan = plan_instruction(_dev(cfg), view)
    assert plan.action == "add"
    commit_instruction(plan, Writer(), tmp_path / "bk")
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert view.as_posix() in data["instructions"] and "a.md" in data["instructions"]
    assert data["model"] == "x"                          # 其余键保留

def test_creates_array_when_absent(tmp_path):
    cfg = tmp_path / "opencode.json"; cfg.write_text("{}", encoding="utf-8")
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    commit_instruction(plan, Writer(), tmp_path / "bk")
    assert "instructions" in json.loads(cfg.read_text(encoding="utf-8"))

def test_dedup_is_present_noop(tmp_path):
    cfg = tmp_path / "opencode.json"; view = tmp_path / "v.md"
    cfg.write_text(json.dumps({"instructions": [view.as_posix()]}), encoding="utf-8")
    plan = plan_instruction(_dev(cfg), view)
    assert plan.action == "present"
    w = Writer(); commit_instruction(plan, w, tmp_path / "bk")
    assert w.written == []

def test_jsonc_refused_no_write(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text('{\n  // comment\n  "model": "x"\n}', encoding="utf-8")
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    assert plan.action == "refuse" and "instructions" in plan.reason
    w = Writer(); commit_instruction(plan, w, tmp_path / "bk")
    assert w.written == []                               # refuse 不写、不抛

def test_instructions_not_a_list_refused_not_overwritten(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"instructions": "one.md"}), encoding="utf-8")  # 是字符串不是数组
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    assert plan.action == "refuse"
    commit_instruction(plan, Writer(), tmp_path / "bk")
    assert json.loads(cfg.read_text(encoding="utf-8"))["instructions"] == "one.md"  # 原值没被覆盖

def test_rollback_log_written_no_key_copy(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"instructions": []}), encoding="utf-8")
    bk = tmp_path / "bk"
    commit_instruction(plan_instruction(_dev(cfg), tmp_path / "v.md"), Writer(), bk)
    logs = list(bk.glob("opencode-*.log"))
    assert logs and "hash" in logs[0].read_text(encoding="utf-8")
    assert not list(bk.glob("*opencode.json"))           # 不复制整份密钥文件

def test_null_instructions_refused_not_overwritten(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"instructions": None}), encoding="utf-8")  # 显式 null，不是缺失
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    assert plan.action == "refuse"
    commit_instruction(plan, Writer(), tmp_path / "bk")
    assert json.loads(cfg.read_text(encoding="utf-8"))["instructions"] is None  # 原值没被覆盖

def test_config_write_failure_leaves_no_log(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"instructions": []}), encoding="utf-8")
    bk = tmp_path / "bk"
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    assert plan.action == "add"

    class FailingWriter(Writer):
        def write_text_atomic(self, path, text):
            raise OSError("simulated config write failure")

    with pytest.raises(OSError):
        commit_instruction(plan, FailingWriter(), bk)
    assert list(bk.glob("opencode-*.log")) == []         # 配置没写成，日志绝不能留下
