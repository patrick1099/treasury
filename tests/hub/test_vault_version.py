import pytest
from hub.vault import require_supported_version, require_version_exactly, UnsupportedVaultVersion

def _v(tmp, n): (tmp/"vault.toml").write_text(f"version = {n}\n", encoding="utf-8")

def test_supported_v3_ok(tmp_path):
    _v(tmp_path, 3); assert require_supported_version(tmp_path) == 3

def test_future_refused(tmp_path):
    _v(tmp_path, 4)
    with pytest.raises(UnsupportedVaultVersion):
        require_supported_version(tmp_path)

def test_exactly_3_required(tmp_path):
    _v(tmp_path, 2)
    with pytest.raises(UnsupportedVaultVersion):
        require_version_exactly(tmp_path, 3)     # 插件命令在 v2 上必须拒绝
