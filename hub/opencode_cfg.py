"""opencode.json 的 instructions[] 写入。该文件含明文密钥（guard 范畴）。

拆成 plan（纯只读）/ commit（写）两段，让编排方能在写任何东西之前完成全量预检。
- 路径：优先 device.toml 的 OPENCODE_CONFIG，缺省 ~/.config/opencode/opencode.json。
- **能严格 json.loads 且 instructions 缺失或是 list[str] 才改**：缺失→创建、list→去重追加。
- 以下一律 refuse（**不抛异常、绝不覆盖**，由编排方降为 warning）：注释/尾逗号/解析失败/读取失败、
  顶层非对象、`instructions` 存在但**不是数组**（含显式 `null`——用哨兵值区分"缺失"和"值是 null"，
  两者都会被静默换成新数组、毁掉用户数据）。
- 保留未知键，但**不声称保留原格式**（json.dumps 会重排版）。
- 不复制整份密钥文件；只写最小回滚日志（路径/改前哈希/原 instructions 是缺失还是具体值/本次条目）。
"""
import hashlib, json, time, uuid
from dataclasses import dataclass
from pathlib import Path
from hub.writer import Writer

_MISSING = object()

@dataclass
class OpencodePlan:
    action: str                     # "present" | "add" | "refuse"
    config_path: Path
    entry: str
    new_text: str | None = None
    log_text: str | None = None
    reason: str | None = None

def opencode_config_path(dev) -> Path:
    p = dev.paths.get("OPENCODE_CONFIG")
    return Path(p) if p else Path.home() / ".config" / "opencode" / "opencode.json"

def _manual(cfg: Path, entry: str, why: str) -> str:
    return (f"{why} hub 不敢重写带密钥的 {cfg}。请手工在 instructions 数组里加一行："
            f"{json.dumps(entry, ensure_ascii=False)}")

def plan_instruction(dev, view_path: Path) -> OpencodePlan:
    cfg = opencode_config_path(dev)
    entry = Path(view_path).as_posix()
    raw = "{}"
    try:
        if cfg.exists():
            raw = cfg.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (ValueError, OSError):           # UnicodeDecodeError⊂ValueError; OSError=权限/IO
        return OpencodePlan("refuse", cfg, entry,
                            reason=_manual(cfg, entry, "不是严格 JSON（可能含注释/尾逗号）或读取失败。"))
    if not isinstance(data, dict):
        return OpencodePlan("refuse", cfg, entry,
                            reason=_manual(cfg, entry, "顶层不是对象。"))
    old = data.get("instructions", _MISSING)
    if old is _MISSING:
        new_list = [entry]
    elif isinstance(old, list):
        if entry in old:
            return OpencodePlan("present", cfg, entry)
        new_list = list(old) + [entry]
    else:                                   # includes null, string, number, object → refuse, never overwrite
        return OpencodePlan("refuse", cfg, entry,
                            reason=_manual(cfg, entry, "instructions 存在但不是数组。"))
    data["instructions"] = new_list
    log = (f"path={cfg}\nhash={hashlib.sha256(raw.encode('utf-8')).hexdigest()}\n"
           f"instructions_before={'MISSING' if old is _MISSING else json.dumps(old, ensure_ascii=False)}\n"
           f"added={entry}\n")
    return OpencodePlan("add", cfg, entry,
                        new_text=json.dumps(data, ensure_ascii=False, indent=2) + "\n", log_text=log)

def commit_instruction(plan: OpencodePlan, w: Writer, backups_dir: Path) -> None:
    if plan.action != "add":
        return
    # 先写配置：若它失败，异常上抛、**不留假日志**（避免"日志说改了、配置其实没动"）。
    w.write_text_atomic(plan.config_path, plan.new_text)
    if plan.log_text:
        # 配置写成功后才记回滚日志；文件名带 uuid，防同秒多次调用互相覆盖。
        name = f"opencode-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.log"
        w.write_text_atomic(backups_dir / name, plan.log_text)
