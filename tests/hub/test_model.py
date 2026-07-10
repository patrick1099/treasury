import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOL_DIR))

from hub.model import Memory, Target, DeviceProfile, ProjectTarget, VaultConfig

def test_memory_defaults():
    m = Memory(name="x", description="d", type="project",
               scope=["global"], portable=True, sensitive=False, body="hi")
    assert m.path is None
    assert m.scope == ["global"]

def test_device_profile_holds_targets():
    dp = DeviceProfile(host="huawei", classes=["work"], projects=["xinao"],
                       paths={"VAULT": "Z:/vault"},
                       targets=[ProjectTarget(project="xinao", root="C:/x")])
    assert dp.targets[0].project == "xinao"
    assert VaultConfig(version=1).version == 1
    assert Target(frozenset({"work"}), "xinao", "claude").tool == "claude"
