import os, tomllib
from dataclasses import dataclass
from pathlib import Path
from hub.writer import Writer

@dataclass
class Baseline: sha: str; version: str

def state_path() -> Path:
    return Path(os.environ.get("HUB_HOME") or (Path.home()/".hub")) / "plugin-state.toml"

def read_state() -> dict:
    p = state_path()
    if not p.exists(): return {}
    raw = tomllib.loads(p.read_text(encoding="utf-8")).get("plugins", {})
    return {n: {t: Baseline(b["sha"], b["version"]) for t, b in tools.items()}
            for n, tools in raw.items()}

def record(name, tool, sha, version, w: Writer) -> None:
    st = read_state()
    st.setdefault(name, {})[tool] = Baseline(sha, version)
    lines = []
    for n, tools in sorted(st.items()):
        for t, b in sorted(tools.items()):
            lines.append(f'[plugins.{n}.{t}]\nsha = "{b.sha}"\nversion = "{b.version}"\n')
    w.write_text_atomic(state_path(), "\n".join(lines))
