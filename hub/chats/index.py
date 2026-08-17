"""SQLite + FTS5 索引：原始对话库的派生层（spec §3/§8）。

派生层随时可以删了重建，所以这里的每一行都必须能指回原始层——session.raw_path
是相对金库根的原始文件路径，event 记 native_id / source_key / last_raw_line /
replay_upto_line，定位符按 spec §8.1 的优先级取（native_id → source_key →
s<seq>）。基线文档要的"从命中回到原消息"全靠这三个字段撑着。

**表结构与 spec §8 逐字一致**，包括 session.host 和 UNIQUE(host, source,
session_id)。event_fts 是 external content 表（content='event',
content_rowid='id'），插入 event 时手动插一行 FTS、**删除 event 时也要手动删
对应的 FTS 行**——只插不删会留下孤儿 FTS 行，搜索命中一条根本不存在的 event，
这就是"索引不可信"。重建（rebuild）直接 DROP 整张 FTS 表再重建，孤儿随表一起
消失，所以重建路径天然干净。

**索引范围**（spec §8，两条最容易做错）：

- 只索引 role=transcript 的 artifact。auxiliary（workspaces.toml /
  workspace.yaml）不建 session、不产 event，只在补 session 工程信息时被读。
  目前实现的是 copilot-vscode 的 workspaces.toml：chatSessions 的 jsonl 里
  没有工程路径，hash 就是废字符串，得靠 <hash> → folder 映射把 cwd 补上。
  copilot-cli 的 workspace.yaml 是 YAML 而 stdlib 没有 YAML 解析器，而且它
  的事件流本身已经带 cwd/gitRoot（parse 层填了），所以只是不索引、不解析。
- 只索引 current，不索引 revisions/。revision 是被取代的旧快照，索引它们会让
  同一段话出现多条重复命中。manifest 里 entry.superseded_by 非空就是 revision，
  直接跳过。这条与 UNIQUE(host, source, session_id) 是配套的：同一会话同一时刻
  只有一份 current 进索引，改 sha 就整体重建，不存在新旧两份并存。

**增量**：库里该 (host, source, session_id) 的 raw_sha 与 manifest 的 sha256
相同 → 跳过（索引已经建在那个版本上）；不同或不存在 → 先删掉这条 session 的
全部 event（**连同 FTS 行**）再重建。manifest 是 append-only 的，条目只会被标
source_gone 不会消失，所以当前 manifest 里没有的 db session 属于陈旧数据，也
一并清掉，索引才不会越攒越脏。

**中文分词**：tokenize='unicode61' **加索引侧逐字切分**（`fts_text`）。

原设计只写 unicode61,实测（本机 3.50.4）它把**连续 CJK 合并成单个 token**——
「超声波流量计标定阈值怎么调」整串是一个词,于是「标定」「阈值」「超声波」**一个都搜不到**。
对一个首要价值就是"跨平台中文检索"的库来说这不是精度折扣,是功能不成立。

实测过的三条路:

    方案                  标定  阈值  超声波  流量计标定  threshold  calib
    unicode61 原样         ✗    ✗     ✗      ✗          ✓         ✗
    trigram                ✗    ✗     ✓      ✓          ✓         ✓
    unicode61 + 逐字切分    ✓    ✓     ✓      ✓          ✓         ✗

trigram 救得了三字以上,但**二字词搜不到**,而中文二字词恰恰最常用,所以不选它。
选逐字切分:写进 FTS 那一列时把每个 CJK 字符两边加空格,每个字成为独立 token,
多字查询就变成 phrase query。**`event.text` 存的仍是原文**,变换只发生在 FTS 索引列。

代价照实说:英文**前缀**匹配没了（`calib` 匹配不到 `calibrate`）——那是 unicode61 本来
就有的行为,不是这次引入的;要前缀匹配用 FTS5 自带的 `calib*` 语法。

**查询侧必须用同一个 `fts_text` 变换**,否则索引切了、查询没切,中文永远零命中。
search 那一层直接 import 这个函数,别自己再写一份。

库的位置走 hubconfig 拿 ~/.hub（hub_config_path().parent，它内部处理 HUB_HOME
环境变量），不自己拼 Path.home()——测试的 autouse 闸把 Path.home() 重定向进
tmp 时，默认库路径会自动跟着落进 tmp。
"""
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path

# 逐字切分要覆盖的区段:CJK 统一表意 + 扩展 A + 兼容表意 + 日文假名。
# 假名也切:Codex/opencode 的对话里出现日文不是稀奇事,而它们同样会被 unicode61
# 粘成一个 token。韩文谚文有词间空格,unicode61 本来就切得开,不必管。
_CJK_RANGES = (
    (0x3040, 0x30FF),      # 平假名 / 片假名
    (0x3400, 0x4DBF),      # CJK 扩展 A
    (0x4E00, 0x9FFF),      # CJK 统一表意
    (0xF900, 0xFAFF),      # CJK 兼容表意
)


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _CJK_RANGES)


def fts_text(s: str) -> str:
    """把 CJK 逐字用空格隔开,供 FTS 索引与查询**两侧共用**。

    unicode61 把连续 CJK 当成一个 token(见模块 docstring 的实测表),隔开之后每个字
    是独立 token,「标定」这样的多字查询就变成 phrase query,能匹配任意位置。

    两侧共用是硬要求:索引切了而查询没切,中文查询会稳定零命中,而且**不报错**——
    那种坏法最难发现。search 直接 import 这个函数,不要各写一份。
    """
    out = []
    for ch in s:
        if _is_cjk(ch):
            out.append(" ")
            out.append(ch)
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)

from hub.chats import paths
from hub.chats.manifest import load as load_manifest
from hub.chats.model import TRANSCRIPT
from hub.chats.parse import parse as parse_source
from hub.chats.sources import SOURCES, UnknownSource
from hub.hubconfig import hub_config_path

_DDL_SESSION = """
CREATE TABLE IF NOT EXISTS session(
  id INTEGER PRIMARY KEY,
  host TEXT NOT NULL,
  source TEXT NOT NULL,
  session_id TEXT NOT NULL,
  started_at INTEGER, ended_at INTEGER,
  cwd TEXT, repo TEXT, branch TEXT,
  model TEXT, title TEXT,
  raw_path TEXT NOT NULL,
  raw_sha TEXT NOT NULL,
  event_count INTEGER,
  UNIQUE(host, source, session_id));
"""

_DDL_EVENT = """
CREATE TABLE IF NOT EXISTS event(
  id INTEGER PRIMARY KEY,
  session INTEGER NOT NULL REFERENCES session(id),
  seq INTEGER NOT NULL,
  native_id TEXT,
  source_key TEXT,
  ts INTEGER,
  role TEXT,
  kind TEXT,
  tool TEXT,
  text TEXT,
  last_raw_line INTEGER NOT NULL,
  replay_upto_line INTEGER,
  UNIQUE(session, seq));
"""

_DDL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
  text, content='event', content_rowid='id', tokenize='unicode61');
"""


@dataclass
class IndexStats:
    sources: int = 0      # 处理了多少个源目录（含没有任何数据的空源）
    sessions: int = 0     # 本次（重新）索引了多少个会话
    unchanged: int = 0    # sha 相同直接跳过的会话
    skipped: int = 0      # 原始文件缺失/解析失败而没进索引的会话


def default_db_path() -> Path:
    """~/.hub/chats-index.db。

    走 hubconfig 的 hub_config_path().parent（= ~/.hub，内部处理 HUB_HOME），
    不自己拼 Path.home()——测试把 home 重定向进 tmp 时默认路径自动跟着走。
    """
    return hub_config_path().parent / "chats-index.db"


def db_counts(db_path: Path) -> tuple[int, int, int]:
    """(session 行数, event 行数, FTS 行数)。测试与 status 核对索引状态用。

    FTS 行数单独给出来，就是为了能直接断言"没留孤儿 FTS 行"——它必须等于
    event 行数，否则就有搜索命中不存在的 event。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        return tuple(
            conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            for tbl in ("session", "event", "event_fts"))
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    for ddl in (_DDL_SESSION, _DDL_EVENT, _DDL_FTS):
        conn.execute(ddl)


def _drop_all(conn: sqlite3.Connection) -> None:
    for tbl in ("event_fts", "event", "session"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")


def _find_session(conn, host: str, source: str, session_id: str):
    return conn.execute(
        "SELECT id, raw_sha FROM session WHERE host=? AND source=? AND session_id=?",
        (host, source, session_id)).fetchone()


def _delete_session_rows(conn, sid: int) -> None:
    """删一个 session 的 event 时连 FTS 行一起删,一个孤儿都不留。

    必须走 FTS5 的 `'delete'` 命令并**把当初索引进去的那份文本原样喂回去**,不能用
    普通 `DELETE FROM event_fts`。原因:FTS 列存的是 `fts_text()` 逐字切分后的文本,
    与 content 表里的 `event.text` 不是同一个串;普通 DELETE 会去 content 表取原文
    重新分词来抵消索引项,抵消的是**错的 token**,倒排里那份切分过的就永远留下了。

    实测(3.50.4):这样留下的孤儿**搜得到、指向已删除的 event,而 `integrity-check`
    还报通过**——没有任何东西会告诉你索引脏了,直到 `show` 拿着一个不存在的 id 去
    回原文。所以这一处不是风格问题。
    """
    rows = conn.execute(
        "SELECT id, text FROM event WHERE session=?", (sid,)).fetchall()
    for eid, text in rows:
        conn.execute("INSERT INTO event_fts(event_fts, rowid, text)"
                     " VALUES ('delete', ?, ?)", (eid, fts_text(text or "")))
    conn.execute("DELETE FROM event WHERE session=?", (sid,))
    conn.execute("DELETE FROM session WHERE id=?", (sid,))


def _delete_session(conn, host: str, source: str, session_id: str) -> None:
    row = _find_session(conn, host, source, session_id)
    if row is not None:
        _delete_session_rows(conn, row[0])


def _aux_workspace_folders(chats: Path, entries: dict) -> dict:
    """copilot-vscode 的 workspaces.toml → {hash: folder}。

    有就返回映射，没有/解析失败返回空 dict——一个坏掉的辅助文件不该让整次索引
    炸掉，工程路径本来就是锦上添花。
    """
    e = entries.get("workspaces.toml")
    if e is None:
        return {}
    try:
        data = tomllib.loads((chats / e.rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ws = data.get("workspaces") if isinstance(data, dict) else None
    return {k: v for k, v in ws.items() if v} if isinstance(ws, dict) else {}


def _enrich_cwd(rel: str, psess, folders: dict) -> None:
    """vscode 会话的 rel 是 sessions/<hash>/<name>.jsonl，用 hash 查 folder 补 cwd。

    只有 parse 没给出 cwd（chatSessions 的 jsonl 里没有工程路径）才补；parse 给
    了就用 parse 的，别拿辅助文件的值覆盖它。
    """
    if psess.cwd or not rel.startswith("sessions/"):
        return
    parts = rel.split("/")
    if len(parts) >= 3 and parts[1] in folders:
        psess.cwd = folders[parts[1]]


def _insert_session(conn, host: str, source: str, session_id: str,
                    entry, psess, raw_rel: str) -> int:
    cur = conn.execute(
        "INSERT INTO session(host, source, session_id, started_at, ended_at,"
        " cwd, repo, branch, model, title, raw_path, raw_sha, event_count)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (host, source, session_id, psess.started_at, psess.ended_at, psess.cwd,
         psess.repo, psess.branch, psess.model, psess.title, raw_rel,
         entry.sha256))
    return cur.lastrowid


def _insert_event(conn, sid: int, ev) -> None:
    cur = conn.execute(
        "INSERT INTO event(session, seq, native_id, source_key, ts, role, kind,"
        " tool, text, last_raw_line, replay_upto_line) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sid, ev.seq, ev.native_id, ev.source_key, ev.ts, ev.role, ev.kind,
         ev.tool, ev.text, ev.last_raw_line, ev.replay_upto_line))
    # FTS 那一列存**逐字切分后**的文本(见 fts_text);event.text 仍是原文。
    # external content 表这里是"手工喂内容",FTS 列与 content 表列不一致是允许的
    # ——检索只用 FTS 列,回显和回原文一律用 event.text。
    conn.execute("INSERT INTO event_fts(rowid, text) VALUES (?,?)",
                 (cur.lastrowid, fts_text(ev.text)))


def _index_source(conn, vault_root: Path, host: str, source: str,
                  stats: IndexStats) -> None:
    chats = paths.chats_dir(vault_root, host, source)
    entries = load_manifest(chats)
    folders = _aux_workspace_folders(chats, entries)
    current = [e for e in entries.values()
               if e.role == TRANSCRIPT and not e.superseded_by]
    current_ids = set()

    for entry in sorted(current, key=lambda e: e.rel):
        session_id = entry.session_id or entry.rel
        current_ids.add(session_id)
        row = _find_session(conn, host, source, session_id)
        if row is not None and row[1] == entry.sha256:
            # 索引已经建在这个版本上，raw_sha 就是证据（spec §8）。
            stats.unchanged += 1
            continue
        if row is not None:
            # sha 变了：旧版本被取代，连同 FTS 行一起删干净再重建。
            _delete_session_rows(conn, row[0])
        raw = Path(chats) / entry.rel
        if not raw.is_file():
            stats.skipped += 1
            continue
        try:
            psess, events = parse_source(source, raw)
        except Exception:
            stats.skipped += 1
            continue
        _enrich_cwd(entry.rel, psess, folders)
        sid = _insert_session(
            conn, host, source, session_id, entry, psess,
            f"{host}/{source}/chats/{entry.rel}")
        for ev in events:
            _insert_event(conn, sid, ev)
        conn.execute("UPDATE session SET event_count=? WHERE id=?",
                     (len(events), sid))
        stats.sessions += 1

    for row in conn.execute(
            "SELECT id, session_id FROM session WHERE host=? AND source=?",
            (host, source)):
        if row[1] not in current_ids:
            _delete_session_rows(conn, row[0])
    stats.sources += 1


def build_index(vault_root: Path, host: str,
                db_path: Path | None = None,
                sources: list[str] | None = None,
                rebuild: bool = False) -> IndexStats:
    """把金库原始层建成 ~/.hub/chats-index.db，返回本次统计。

    - `sources=None` 时处理全部五个源；给了名字就只处理那些。
    - `rebuild=True` 先 DROP 所有表再全量重建（--rebuild）。
    - 同 (host, source, session_id) 的 raw_sha 与 manifest 一致 → 跳过；
      不一致/不存在 → 先删干净（含 FTS 行）再重建。
    任何异常都回滚整个事务：索引是派生物，宁可整体停在旧版本等下次重跑，
    也不能留一半新一半旧的自相矛盾状态。
    """
    db = Path(db_path) if db_path is not None else default_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        if rebuild:
            _drop_all(conn)
        _init_schema(conn)
        names = list(sources) if sources else list(SOURCES)
        for name in names:
            if name not in SOURCES:
                raise UnknownSource(
                    f"不认识的对话源 {name!r};已知的是 {sorted(SOURCES)}")
        stats = IndexStats()
        for name in names:
            _index_source(conn, vault_root, host, name, stats)
        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
