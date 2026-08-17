"""opencode 的会话发现:从 ~/.local/share/opencode/opencode.db 导出对话。

opencode 跟别的源最根本的区别:它**没有文件可拷**。旧版 storage/ 目录已基本被
清空,对话正文全在 SQLite 里。所以对这个源,"原样复制"不成立,只能**导出**——
导出的是**原字段的原始行**,不是我们翻译过的模型,否则"原始证据库"这个承诺就破了
(spec §2 / §4.3)。

约束:
- **只读打开**(`?mode=ro`),绝不写源库、绝不 VACUUM、绝不建索引。
- 只导出 session / message / part 三张表。`event` 表是与 message/part 重复的
  事件流(真机 3 万行),不导出——导出它等于把同一份内容存两遍,还让幂等判据
  (两次导出字节相同)被这种重复流污染。
- 行序必须确定:session 在最前,message 与 part 混排按 `(time_created, id)` 升序。
  SQLite 行本来没有保证顺序(除非显式 ORDER BY),拿到什么顺序就落盘什么字节,
  append-only 的幂等当场失效——所以必须显式排。
- message / part 的 `data` 列在库里是 JSON 字符串,解析后**原样内联**(不是再套
  一层字符串);解析失败保留原串并加 `_data_unparsed: true`,**不许丢**——丢了就
  再也回不去了。

列名用 `SELECT *` 白拿,不写死列清单:真机 schema 的 session 表有一长串可空列,
硬编码列名既笨又容易在 opencode 升级加列时漏掉新列。`cursor.description` 给出的是
建表时的列序,`dict(row)` 保持这个顺序——同一张表两次导出列序一致,字节也就一致。

`require_source` 复用的是 T4 的缺源规则:根目录是"已配置"的,库文件不在就是配置
坏了,必须抛,不许解释成"这个源没有会话"(那会让 append-only 状态机把整个源标成
source_gone)。
"""
import json
import sqlite3
from pathlib import Path

from ..model import Artifact, GENERATED, TRANSCRIPT
from ...guard import check_source
from ...collect.errors import require_source

NAME = "opencode"
DB_NAME = "opencode.db"


def _inline(row, table):
    """把一行转成导出对象:`_row` 打头,message/part 的 data 解析后内联。"""
    out = dict(row)
    raw = out.get("data")
    if isinstance(raw, str):
        try:
            out["data"] = json.loads(raw)
        except (TypeError, ValueError):
            out["_data_unparsed"] = True
    return {"_row": table, **out}


def _sort_key(r):
    ts = r["time_created"]
    return (ts if ts is not None else -1, r["id"])


def _line(row, table):
    return json.dumps(_inline(row, table), ensure_ascii=False, separators=(",", ":"))


def discover(root: Path) -> list[Artifact]:
    check_source(root)
    db = require_source(root / DB_NAME, f"{NAME} 数据库", kind="file")
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    arts = []
    try:
        con.row_factory = sqlite3.Row
        for srow in con.execute("SELECT * FROM session ORDER BY id"):
            sid = srow["id"]
            msgs = con.execute(
                "SELECT * FROM message WHERE session_id = ?",
                (sid,)).fetchall()
            parts = con.execute(
                "SELECT * FROM part WHERE session_id = ?",
                (sid,)).fetchall()
            tagged = [("message", r) for r in msgs] + [("part", r) for r in parts]
            tagged.sort(key=lambda p: _sort_key(p[1]))
            tagged = [("session", srow)] + tagged
            lines = [_line(r, t) for t, r in tagged]
            text = "".join(l + "\n" for l in lines)
            arts.append(Artifact(
                rel=f"sessions/{sid}.jsonl",
                session_id=str(sid),
                kind=GENERATED,
                role=TRANSCRIPT,
                payload=text.encode("utf-8"),
                lines=len(lines),
            ))
    finally:
        con.close()
    return arts