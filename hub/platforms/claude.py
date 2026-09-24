"""Claude Code。插件走 `claude plugin` CLI；记忆视图用 CLAUDE.md 受管块里的一行 @import 接进去。"""
from pathlib import Path

from hub.platforms._cli import CliPlatform
from hub.platforms.base import Wiring


def block_state(f: Path) -> str:
    """受管块必须**良构**（恰一对标记），不能只 "hub:begin" in text 就算 ok。"""
    from hub.textblock import has_one_valid_block
    if not f.exists():
        return "missing"
    t = f.read_text(encoding="utf-8")
    if has_one_valid_block(t):
        return "ok"
    return "malformed" if ("hub:begin" in t or "hub:end" in t) else "missing"


class Claude(CliPlatform):
    name = "claude"
    cli_dialect = "claude"
    cli_has_disable = True          # claude plugin disable：装着但不启用
    skills_home_key = "CLAUDE_HOME"
    skills_home_desc = "claude 技能目录"

    def skills_home(self, dev):
        home = dev.paths.get("CLAUDE_HOME")
        return Path(home) / "skills" if home else None

    def bootstrap_dir(self, dev):
        return self.skills_home(dev)

    def prepare_wiring(self, ctx):
        from hub.textblock import upsert_block
        home = ctx.dev.paths.get("CLAUDE_HOME")
        if not home:
            return Wiring()
        claude_md = Path(home) / "CLAUDE.md"
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        body = f"# hub 共享记忆（自动生成，勿手改）\n@{ctx.view_path(self.name).as_posix()}"
        return Wiring(writes=[(claude_md, upsert_block(existing, body))])   # 坏块→BlockError（预检期）

    def wiring_health(self, dev, cur_hash):
        home = dev.paths.get("CLAUDE_HOME")
        if not home:
            return []
        cm = Path(home) / "CLAUDE.md"
        return [(block_state(cm), str(cm))]


ADAPTER = Claude()
