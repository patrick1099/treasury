from pathlib import Path
from hub.vault import load_vault, load_device
from hub.model import Vault, DeviceProfile  # Vault 从 model 或 vault 导出——见实现

def _mk_vault(root: Path):
    (root / "rules").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "devices").mkdir()
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / "rules" / "b.md").write_text("规则B\n", encoding="utf-8")
    (root / "rules" / "a.md").write_text("规则A\n", encoding="utf-8")
    (root / "memory" / "m1.md").write_text(
        "---\nname: m1\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n",
        encoding="utf-8")
    (root / "devices" / "huawei.toml").write_text(
        'class = ["work"]\nprojects = ["xinao"]\n\n'
        '[paths]\nVAULT = "Z:/vault"\n\n'
        '[[targets]]\nproject = "xinao"\nroot = "C:/x"\n',
        encoding="utf-8")

def test_load_vault(tmp_path):
    _mk_vault(tmp_path)
    v = load_vault(tmp_path)
    assert v.config.version == 1
    assert [name for name, _ in v.rules] == ["a", "b"]  # 排序
    assert len(v.memories) == 1 and v.memories[0].name == "m1"

def test_load_device(tmp_path):
    _mk_vault(tmp_path)
    dp = load_device(tmp_path, "huawei")
    assert dp.classes == ["work"]
    assert dp.paths["VAULT"] == "Z:/vault"
    assert dp.targets[0].project == "xinao" and dp.targets[0].root == "C:/x"
