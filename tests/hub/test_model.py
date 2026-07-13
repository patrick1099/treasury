from hub.model import Memory, Target, DeviceProfile, ToolSources, VaultConfig, Vault, SHARED

def test_memory_defaults():
    m = Memory(name="x", description="d", type="project",
               scope=["global"], portable=True, sensitive=False, body="hi")
    assert m.path is None
    assert m.origin is None
    assert m.scope == ["global"]

def test_tool_sources_missing_fields_mean_not_installed():
    ts = ToolSources()
    assert ts.memory == []
    assert ts.skills is None
    assert ts.plugin_repos is None
    assert ts.settings is None
    assert ts.agents is None

def test_device_profile_sources_split_by_tool():
    dp = DeviceProfile(host="huawei", classes=["work"], projects=["xinao"],
                       paths={"CLAUDE_HOME": "C:/x/.claude"},
                       sources={"claude": ToolSources(skills="C:/x/.claude/skills")})
    assert dp.sources["claude"].skills == "C:/x/.claude/skills"
    assert "codex" not in dp.sources
    assert VaultConfig(version=1).version == 1
    assert Target(frozenset({"work"}), "xinao", "claude").tool == "claude"

def test_device_profile_sources_default_empty():
    dp = DeviceProfile(host="h", classes=[], projects=[], paths={})
    assert dp.sources == {}

def test_vault_has_no_rules_field():
    v = Vault(root=".", config=VaultConfig(version=1), memories=[])
    assert not hasattr(v, "rules")
