"""T9 索引层测试：建库→索引→计数；幂等；sha 变了重建不留孤儿；rebuild；FTS 中英文；revisions/auxiliary 不进索引。

判据来自 spec §8 与计划 T9：
- 只索引 role=transcript 的 current；revision（superseded_by 非空）与 auxiliary 都不建 session。
- 同 (host, source, session_id) 的 raw_sha 与 manifest 一致 → 跳过，零变化。
- sha 变了 → 删掉该 session 全部 event（**连同 FTS 行**）再重建，不留孤儿。
- event_fts 是 external content 表，event 与 fts 行数必须相等，否则搜索会命中不存在的 event。
"""
import sqlite3

import pytest

from hub.chats.index import build_index, db_counts, default_db_path, fts_text
from hub.chats.manifest import dump
from hub.chats.model import AUXILIARY, TRANSCRIPT, Entry
from hub.digest import digest_file

HOST = "h1"


def _vault(tmp_path):
    return tmp_path / "vault"


def _db(tmp_path):
    return tmp_path / "index.db"


def _entry(rel, sha, session_id, role=TRANSCRIPT, superseded_by="", kind="copy"):
    return Entry(rel=rel, role=role, kind=kind, sha256=sha, session_id=session_id,
                 superseded_by=superseded_by)


def _put(chats, rel, text):
    p = chats / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _commit(chats, entries):
    (chats / "manifest.toml").write_text(dump(entries), encoding="utf-8")


def test_build_index_counts_and_rows(tmp_path):
    chats = _vault(tmp_path) / HOST / "claude" / "chats"
    user = ('{"type":"user","uuid":"u1","timestamp":"2026-08-01T01:00:00.000Z",'
            '"sessionId":"s1","message":{"role":"user","content":[{"type":"text",'
            '"text":"如何配置 git hook"}]}}\n')
    assistant = ('{"type":"assistant","uuid":"a1","timestamp":"2026-08-01T01:00:01.000Z",'
                 '"sessionId":"s1","message":{"role":"assistant","model":"claude-x",'
            '"content":[{"type":"text","text":"用 pre-commit 脚本处理 git hook 的 调用"}]}}\n')
    rel = "sessions/s1.jsonl"
    p = _put(chats, rel, user + assistant)
    _commit(chats, {"sessions/s1.jsonl": _entry(rel, digest_file(p).sha256, "s1")})

    stats = build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])

    assert stats.sessions == 1
    assert stats.unchanged == 0
    assert db_counts(_db(tmp_path)) == (1, 2, 2)      # 1 session, 2 events, 2 fts 行

    conn = sqlite3.connect(str(_db(tmp_path)))
    row = conn.execute(
        "SELECT host, source, session_id, raw_sha, event_count, raw_path"
        " FROM session").fetchone()
    assert row[0] == HOST and row[1] == "claude" and row[2] == "s1"
    assert row[4] == 2
    assert row[5] == f"{HOST}/claude/chats/{rel}"
    conn.close()


def test_second_index_same_sha_zero_change(tmp_path):
    chats = _vault(tmp_path) / HOST / "claude" / "chats"
    rel = "sessions/s1.jsonl"
    user = ('{"type":"user","uuid":"u1","timestamp":"2026-08-01T01:00:00.000Z",'
            '"sessionId":"s1","message":{"role":"user","content":[{"type":"text",'
            '"text":"如何配置 git hook"}]}}\n')
    p = _put(chats, rel, user)
    _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})

    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])
    before = db_counts(_db(tmp_path))

    stats = build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])
    assert stats.sessions == 0
    assert stats.unchanged == 1
    assert db_counts(_db(tmp_path)) == before


def test_sha_change_rebuilds_without_orphans(tmp_path):
    """sha 变了 → 旧 event 连同 FTS 行一起删掉重建；不留孤儿，旧文本搜不到。"""
    chats = _vault(tmp_path) / HOST / "claude" / "chats"
    rel = "sessions/s1.jsonl"
    old = ('{"type":"user","uuid":"u1","timestamp":"2026-08-01T01:00:00.000Z",'
           '"sessionId":"s1","message":{"role":"user","content":[{"type":"text",'
           '"text":"如何配置 git hook"}]}}\n')
    p = _put(chats, rel, old)
    _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})
    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])
    assert db_counts(_db(tmp_path)) == (1, 1, 1)

    new = ('{"type":"user","uuid":"n1","timestamp":"2026-08-01T01:00:00.000Z",'
           '"sessionId":"s1","message":{"role":"user","content":[{"type":"text",'
           '"text":"索引 重建"}]}}\n')
    p.write_text(new, encoding="utf-8")
    _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})

    stats = build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])
    assert stats.sessions == 1
    assert db_counts(_db(tmp_path)) == (1, 1, 1)       # 旧 event 删了,不留孤儿 fts
    conn = sqlite3.connect(str(_db(tmp_path)))
    assert conn.execute("SELECT count(*) FROM event_fts"
                        " WHERE event_fts MATCH 'git'").fetchone()[0] == 0
    assert _match(conn, "索引") == 1        # 中文查询走与索引侧同一个变换
    conn.close()


def test_rebuild_counts_consistent(tmp_path):
    vault = _vault(tmp_path)
    for src in ("claude", "codex"):
        chats = vault / HOST / src / "chats"
        rel = "sessions/s1.jsonl"
        body = ('{"type":"user","uuid":"u1","timestamp":"2026-08-01T01:00:00.000Z",'
                '"sessionId":"s1","message":{"role":"user","content":[{"type":"text",'
                '"text":"hello"}]}}\n')
        p = _put(chats, rel, body)
        _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})

    build_index(vault, HOST, db_path=_db(tmp_path), sources=["claude", "codex"])
    before = db_counts(_db(tmp_path))

    stats = build_index(vault, HOST, db_path=_db(tmp_path),
                        sources=["claude", "codex"], rebuild=True)
    assert stats.sessions == 2
    assert db_counts(_db(tmp_path)) == before


def test_fts_searches_chinese_and_english(tmp_path):
    """中文与英文都能全文命中；中文是连续字符合并成单个 token（unicode61 的已知折扣）。"""
    chats = _vault(tmp_path) / HOST / "claude" / "chats"
    rel = "sessions/s1.jsonl"
    body = ('{"type":"user","uuid":"u1","timestamp":"2026-08-01T01:00:00.000Z",'
            '"sessionId":"s1","message":{"role":"user","content":[{"type":"text",'
            '"text":"如何配置 git hook"}]}}\n'
            '{"type":"assistant","uuid":"a1","timestamp":"2026-08-01T01:00:01.000Z",'
            '"sessionId":"s1","message":{"role":"assistant","model":"claude-x",'
            '"content":[{"type":"text","text":"用 pre-commit 脚本处理 git hook 的 调用"}]}}\n')
    p = _put(chats, rel, body)
    _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})
    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])

    conn = sqlite3.connect(str(_db(tmp_path)))
    assert conn.execute("SELECT count(*) FROM event_fts"
                        " WHERE event_fts MATCH 'git'").fetchone()[0] == 2
    # 中文查询**必须过 fts_text**（与索引侧同一个变换）。不过的话稳定零命中且不报错。
    assert _match(conn, "脚本处理") == 1
    assert _match(conn, "调用") == 1
    assert _match(conn, "脚本") == 1          # 逐字切分之后,子串也搜得到了
    assert _match(conn, "pre-commit 脚本处理") == 1     # 中英混排的连续子串
    conn.close()

def _cjk_index(tmp_path, text: str):
    """把一段文本索引进去，返回连上的 db。"""
    chats = _vault(tmp_path) / HOST / "claude" / "chats"
    rel = "sessions/s1.jsonl"
    body = ('{"type":"assistant","uuid":"a1","timestamp":"2026-08-01T01:00:01.000Z",'
            '"sessionId":"s1","message":{"role":"assistant","model":"claude-x",'
            '"content":[{"type":"text","text":"' + text + '"}]}}\n')
    p = _put(chats, rel, body)
    _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})
    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])
    return sqlite3.connect(str(_db(tmp_path)))


def _match(conn, q: str) -> int:
    """按查询侧应有的方式搜：与索引侧共用同一个 fts_text 变换。"""
    seg = fts_text(q).strip()
    expr = '"' + seg + '"' if " " in seg else seg
    return conn.execute("SELECT count(*) FROM event_fts WHERE event_fts MATCH ?",
                        (expr,)).fetchone()[0]


def test_cjk_substring_search_works(tmp_path):
    """中文任意子串都搜得到——包括最常用的二字词。

    这条锁的是 spec §8 被实测推翻的那个假设:原设计只用 unicode61,以为它"按字切"。
    实际它把**连续 CJK 合并成一个 token**,于是「超声波流量计标定阈值怎么调」整串
    是一个词,「标定」「阈值」「超声波」一个都搜不到 —— 对一个首要价值就是跨平台
    中文检索的库,那不是精度折扣,是功能不成立。
    修法是索引侧逐字切分(fts_text),查询侧用同一个函数。trigram 也试过,它救得了
    三字以上但**二字词搜不到**,而中文二字词最常用,所以没选。
    """
    conn = _cjk_index(tmp_path, "超声波流量计标定阈值怎么调 calibrate threshold")
    assert _match(conn, "标定") == 1          # 二字词,trigram 方案救不了的那类
    assert _match(conn, "阈值") == 1
    assert _match(conn, "超声波") == 1
    assert _match(conn, "流量计标定") == 1     # 跨"词"的连续子串
    assert _match(conn, "threshold") == 1     # 英文整词照旧
    assert _match(conn, "不存在的词") == 0     # 不是什么都命中
    conn.close()


def test_reindex_leaves_no_orphan_fts_rows(tmp_path):
    """重建索引后,旧文本必须一条都搜不到。

    这条钉的是一个**不会自己暴露**的坏法:FTS 列存的是切分过的文本,与 content 表里的
    event.text 不是同一个串,所以普通 `DELETE FROM event_fts` 会去 content 表取原文
    重新分词来抵消——抵消的是错的 token,切分过的那份永远留在倒排里。实测(3.50.4):
    这种孤儿**搜得到、指向已删除的 event,而 `integrity-check` 还报通过**。
    只有走 FTS5 的 'delete' 命令、把当初索引进去的那份文本原样喂回去才真的删掉。
    """
    chats = _vault(tmp_path) / HOST / "claude" / "chats"
    rel = "sessions/s1.jsonl"
    head = ('{"type":"assistant","uuid":"a1","timestamp":"2026-08-01T01:00:01.000Z",'
            '"sessionId":"s1","message":{"role":"assistant","model":"claude-x",'
            '"content":[{"type":"text","text":"')
    p = _put(chats, rel, head + '旧的标定值' + '"}]}}\n')
    _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})
    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])

    p = _put(chats, rel, head + '新的阈值' + '"}]}}\n')      # 内容换了 → sha 变
    _commit(chats, {rel: _entry(rel, digest_file(p).sha256, "s1")})
    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])

    conn = sqlite3.connect(str(_db(tmp_path)))
    assert _match(conn, "阈值") == 1
    assert _match(conn, "标定") == 0          # 旧文本必须彻底消失,不留孤儿
    n_event = conn.execute("SELECT count(*) FROM event").fetchone()[0]
    n_fts = conn.execute("SELECT count(*) FROM event_fts").fetchone()[0]
    assert n_event == n_fts                  # 两边行数必须相等
    conn.close()


def test_revisions_and_auxiliary_not_indexed(tmp_path):
    chats = _vault(tmp_path) / HOST / "claude" / "chats"
    rel = "sessions/s1.jsonl"
    body = ('{"type":"user","uuid":"u1","timestamp":"2026-08-01T01:00:00.000Z",'
            '"sessionId":"s1","message":{"role":"user","content":[{"type":"text",'
            '"text":"当前版本"}]}}\n')
    p = _put(chats, rel, body)
    rev = "revisions/sessions__s1.jsonl.01234567.jsonl"
    entries = {
        rel: _entry(rel, digest_file(p).sha256, "s1"),
        rev: _entry(rev, "0" * 64, "s1", superseded_by=rel),
        "workspaces.toml": Entry(rel="workspaces.toml", role=AUXILIARY,
                                 kind="generated", sha256="1" * 64,
                                 session_id=""),
    }
    _commit(chats, entries)
    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path), sources=["claude"])

    # revision 和 auxiliary 都不建 session：只有 current transcript 那 1 个会话
    assert db_counts(_db(tmp_path)) == (1, 1, 1)
    conn = sqlite3.connect(str(_db(tmp_path)))
    assert conn.execute("SELECT count(*) FROM session").fetchone()[0] == 1
    conn.close()


def test_vscode_aux_cwd_filled_from_workspaces_toml(tmp_path):
    """copilot-vscode 的 chatSessions 没有工程路径，cwd 从 workspaces.toml 的 hash 映射补。"""
    chats = _vault(tmp_path) / HOST / "copilot-vscode" / "chats"
    rel = "sessions/abc123/vs-1.jsonl"
    body = ('{"kind":0,"v":{"version":3,"sessionId":"vs-1","requests":[],"pendingRequests":[]}}\n'
            '{"kind":2,"k":["requests"],"v":[{"requestId":"r1","timestamp":1100,'
            '"message":{"text":"你好"},"response":[{"kind":"markdownContent",'
            '"content":"回答"}],"responseId":"res1"}]}\n')
    p = _put(chats, rel, body)
    _put(chats, "workspaces.toml", '[workspaces]\nabc123 = "file:///C:/Users/x/proj"\n')
    entries = {
        rel: _entry(rel, digest_file(p).sha256, "vs-1"),
        "workspaces.toml": Entry(rel="workspaces.toml", role=AUXILIARY,
                                 kind="generated", sha256="2" * 64, session_id=""),
    }
    _commit(chats, entries)
    build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path),
                sources=["copilot-vscode"])

    conn = sqlite3.connect(str(_db(tmp_path)))
    row = conn.execute("SELECT cwd, source, session_id FROM session").fetchone()
    assert row == ("file:///C:/Users/x/proj", "copilot-vscode", "vs-1")
    conn.close()


def test_unknown_source_raises(tmp_path):
    from hub.chats.sources import UnknownSource
    with pytest.raises(UnknownSource):
        build_index(_vault(tmp_path), HOST, db_path=_db(tmp_path),
                    sources=["nope"])


def test_default_db_path_lives_under_hub_home(tmp_path):
    """默认库路径走 hubconfig（autouse 闸把 Path.home() 重定向进 tmp），不落真机 ~/.hub。"""
    p = default_db_path()
    assert p.name == "chats-index.db"
    assert ".hub" in p.parts
    # fake_home 是 tmp_path_factory 造的目录,后面跟着序号(fake_home0/1/2…)
    assert any(part.startswith("fake_home") for part in p.parts)
