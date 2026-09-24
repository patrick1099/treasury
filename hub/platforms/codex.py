"""Codex。插件走 `codex plugin` CLI（没有独立禁用，关掉就是卸载）；记忆视图内联进 AGENTS.md 受管块。"""
from pathlib import Path

from hub.platforms._cli import CliPlatform
from hub.platforms.base import Wiring


def agents_target(dev) -> Path:
    """Codex 受管块目标：活动的非空 AGENTS.override.md 优先，否则 AGENTS.md。"""
    home = Path(dev.paths["CODEX_HOME"])
    override = home / "AGENTS.override.md"
    if override.exists() and override.read_text(encoding="utf-8").strip():
        return override
    return home / "AGENTS.md"


def hash_block_state(f: Path, cur: str) -> str:
    """受管块良构之外还要验**版本**。只验良构有个洞——四个视图写完了、写 AGENTS.md 时失败，
    状态仍会误报全绿。块内嵌 shared_hash 后与当前 shared 比对：hash 是内容线，结构是结构线。"""
    from hub.textblock import has_one_valid_block, valid_block_body
    if not f.exists():
        return "missing"
    t = f.read_text(encoding="utf-8")
    if not has_one_valid_block(t):
        return "malformed" if ("hub:begin" in t or "hub:end" in t) else "missing"
    body = valid_block_body(t) or ""
    embedded = ""
    for line in body.splitlines():
        if "shared_hash:" in line:
            embedded = line.split("shared_hash:")[1].replace("-->", "").strip()
            break
    return "ok" if embedded == cur else "stale"


class Codex(CliPlatform):
    name = "codex"
    cli_dialect = "codex"
    cli_has_disable = False
    skills_home_key = "AGENTS_HOME"
    skills_home_desc = "codex/AGENTS 技能目录"

    def skills_home(self, dev):
        v = dev.paths.get("AGENTS_HOME")
        return (Path(v) if v else Path.home() / ".agents") / "skills"

    def bootstrap_dir(self, dev):
        home = dev.paths.get("CODEX_HOME")
        return Path(home) / "skills" if home else None

    def prepare_wiring(self, ctx):
        from hub.memview import render_codex_block
        from hub.textblock import upsert_block
        if not ctx.dev.paths.get("CODEX_HOME"):
            return Wiring()
        target = agents_target(ctx.dev)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        block = render_codex_block(ctx.per_tool[self.name], ctx.shared_hash)
        return Wiring(writes=[(target, upsert_block(existing, block))])

    def wiring_health(self, dev, cur_hash):
        if not dev.paths.get("CODEX_HOME"):
            return []
        tgt = agents_target(dev)                    # Codex **活动**块（override 优先）
        return [(hash_block_state(tgt, cur_hash), str(tgt))]


ADAPTER = Codex()
