from pathlib import Path
from hub.vault import load_vault, load_device, load_device_rules
from hub.model import Vault, DeviceProfile  # Vault 从 model 或 vault 导出——见实现

def _mem(name: str) -> str:
    return (f"---\nname: {name}\ndescription: d\nmetadata:\n  type: project\n"
            f"  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n")

def _mk_vault(root: Path):
    """金库顶层按归属切:shared/ + 各设备文件夹。"""
    (root / "shared" / "rules").mkdir(parents=True)
    (root / "shared" / "memory").mkdir()
    (root / "huawei" / "memory").mkdir(parents=True)
    (root / "huawei" / "rules").mkdir()
    (root / "h2" / "memory").mkdir(parents=True)
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / "shared" / "rules" / "b.md").write_text("规则B\n", encoding="utf-8")
    (root / "shared" / "rules" / "a.md").write_text("规则A\n", encoding="utf-8")
    (root / "huawei" / "rules" / "local.md").write_text("本机私有规则\n", encoding="utf-8")
    (root / "shared" / "memory" / "common.md").write_text(_mem("common"), encoding="utf-8")
    (root / "huawei" / "memory" / "m1.md").write_text(_mem("m1"), encoding="utf-8")
    (root / "h2" / "memory" / "theirs.md").write_text(_mem("theirs"), encoding="utf-8")
    (root / "huawei" / "device.toml").write_text(
        'class = ["work"]\nprojects = ["xinao"]\n\n'
        '[paths]\nVAULT = "Z:/vault"\n\n'
        '[[targets]]\nproject = "xinao"\nroot = "C:/x"\n',
        encoding="utf-8")

def test_load_vault(tmp_path):
    _mk_vault(tmp_path)
    v = load_vault(tmp_path)
    assert v.config.version == 1
    assert [name for name, _ in v.rules] == ["a", "b"]   # 只取公共规则，排序
    # 各归属文件夹的记忆都读进来，origin 标出它是谁的
    assert {(m.name, m.origin) for m in v.memories} == {
        ("common", "shared"), ("m1", "huawei"), ("theirs", "h2")}

def test_device_rules_are_separate_from_shared(tmp_path):
    _mk_vault(tmp_path)
    assert [n for n, _ in load_device_rules(tmp_path, "huawei")] == ["local"]

def test_load_device(tmp_path):
    _mk_vault(tmp_path)
    dp = load_device(tmp_path, "huawei")
    assert dp.classes == ["work"]
    assert dp.paths["VAULT"] == "Z:/vault"
    assert dp.targets[0].project == "xinao" and dp.targets[0].root == "C:/x"
