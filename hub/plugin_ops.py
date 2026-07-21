from dataclasses import dataclass, field
from pathlib import Path
from hub.plugin_cli import run_cli
from hub.plugin_state import record
from hub.writer import Writer

@dataclass
class PluginAction:
    id: str; describe: str; depends_on: tuple = ()
    cli: object = None; state: tuple = None

@dataclass
class PluginPlan:
    actions: list; warnings: list

@dataclass
class PluginRunReport:
    succeeded: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)

def execute_plugin_plan(plan: PluginPlan, w: Writer, runner=None) -> PluginRunReport:
    rep = PluginRunReport()
    if w.dry_run:
        for a in plan.actions:
            print(f"  [plan] {a.describe}" + (f"  $ {a.cli.tool} {' '.join(a.cli.argv)}" if a.cli else ""))
        return rep
    for a in plan.actions:
        if any(d not in rep.succeeded for d in a.depends_on):
            rep.skipped.append(a.id); continue
        try:
            if a.cli is not None:
                r = run_cli(a.cli, runner=runner)
                if r.returncode != 0:
                    rep.failed.append((a.id, r.stderr.strip() or f"exit {r.returncode}"))
                    continue
            if a.state is not None:
                record(*a.state, w)
            rep.succeeded.append(a.id)
        except Exception as e:
            rep.failed.append((a.id,str(e)))
    return rep
