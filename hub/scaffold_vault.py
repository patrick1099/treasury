"""脚手架:建一个空金库(两区结构 + SCHEMA.md)。"""
from pathlib import Path
from hub.schema_md import SCHEMA_MD
from hub.writer import Writer

_SHARED_DIRS = ["memory", "skills", "plugins", "hooks", "chats"]
_CLAUDE_DIRS = ["memory", "skills", "plugins", "hooks", "chats"]
_CODEX_DIRS = ["skills", "hooks", "chats"]

_DEVICE_TOML = """# 本机档案。缺的项 = 本机没有那个工具/那个源，不是错误。
class = ["work"]
projects = []

[paths]
VAULT = "<金库路径>"
CLAUDE_HOME = "<~/.claude 的绝对路径>"
CODEX_HOME = "<~/.codex 的绝对路径>"

[sources.claude]
memory = ["<~/.claude/projects/<工程编码>/memory>"]
skills = "<~/.claude/skills>"
plugin_repos = "<~/.claude/plugins-dev>"   # 自己写的插件仓所在目录
settings = "<~/.claude/settings.json>"
agents = "<~/.claude/CLAUDE.md>"

[sources.codex]
skills = "<~/.codex/skills>"
settings = "<~/.codex/config.toml>"
agents = "<~/.codex/AGENTS.md>"
# 注：~/.codex/memories/ 不收 —— 生成态，见 SCHEMA.md
"""

def scaffold(root: Path, host: str, w: Writer) -> None:
    root = Path(root)
    w.write_text(root / "vault.toml", "version = 1\n")
    w.write_text(root / "SCHEMA.md", SCHEMA_MD)
    w.write_text(root / "lint-exempt.txt",
                 "# 一行一个记忆 name：豁免裸路径检查（scope 与 sensitive 仍硬拦）\n")
    for d in _SHARED_DIRS:
        w.write_text(root / "shared" / d / ".gitkeep", "")
    for d in _CLAUDE_DIRS:
        w.write_text(root / host / "claude" / d / ".gitkeep", "")
    for d in _CODEX_DIRS:
        w.write_text(root / host / "codex" / d / ".gitkeep", "")
    w.write_text(root / host / "device.toml", _DEVICE_TOML)

if __name__ == "__main__":
    import sys
    scaffold(Path(sys.argv[1]), sys.argv[2], Writer())
    print(f"金库已建在 {sys.argv[1]}，设备 {sys.argv[2]}。先填 device.toml 里的 <…> 占位。")
