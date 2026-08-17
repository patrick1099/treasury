"""T3 的 append-only 状态机测试:四态 + dry-run + 幂等 + verify + GENERATED revision。

判据来自 spec §5 与计划 T3:
- 快路径 (size, mtime) 命中 → unchanged,连 sha 都不算;verify=True 跳过它。
- COPY 新 size > 旧 size 且前缀 sha 相等 → grown,覆盖 current,不留 revision。
- 前缀证明不了 → preserved:旧证据改名进 revisions/,current 记 supersedes。
- GENERATED 没有增长证明,sha 一变一律 preserved(v1 行数判据已作废)。
- 源侧没了 → source_gone=True,文件一个字节不动。
"""
import datetime
import pathlib

import pytest

from hub.chats.collect import collect_source
from hub.chats.manifest import load
from hub.chats.model import Artifact, COPY, GENERATED, TRANSCRIPT
from hub.digest import digest_bytes, digest_file
from hub.writer import Writer


def _copy(rel, src, session_id="s1", **meta):
    return Artifact(rel=rel, session_id=session_id, kind=COPY, role=TRANSCRIPT,
                    src=src, meta=meta)


def _generated(rel, payload, session_id="g"):
    return Artifact(rel=rel, session_id=session_id, kind=GENERATED,
                    role=TRANSCRIPT, payload=payload, lines=payload.count(b"\n"))


def _make_src(tmp_path, data):
    src = tmp_path / "s" / "a.jsonl"
    src.parent.mkdir(parents=True)
    src.write_bytes(data)
    return src


def test_new_copy_artifact_writes_and_manifests(tmp_path):
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    w = Writer()
    rep = collect_source("t", [_copy("sessions/a.jsonl", src)], chats, w)

    assert rep.new == ["sessions/a.jsonl"]
    assert rep.unchanged == []
    assert (chats / "sessions" / "a.jsonl").read_bytes() == b'{"a":1}\n'

    e = load(chats)["sessions/a.jsonl"]
    assert e.sha256 == digest_file(src).sha256
    assert e.bytes == len(b'{"a":1}\n')
    assert e.source_path == str(src)
    assert e.kind == COPY
    assert e.source_gone is False
    # imported_at 存在且可解析,不断言具体时刻
    datetime.datetime.strptime(e.imported_at, "%Y-%m-%dT%H:%M:%SZ")


def test_idempotent_second_run_writes_nothing(tmp_path):
    """幂等硬指标:连跑两次,第二次 w.written == []。"""
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    arts = [_copy("sessions/a.jsonl", src)]

    rep1 = collect_source("t", arts, chats, Writer())
    assert rep1.new == ["sessions/a.jsonl"]

    w2 = Writer()
    rep2 = collect_source("t", arts, chats, w2)
    assert rep2.unchanged == ["sessions/a.jsonl"]
    assert w2.written == []


def test_copy_grown_on_pure_append(tmp_path):
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    arts = [_copy("sessions/a.jsonl", src)]
    collect_source("t", arts, chats, Writer())

    with open(src, "ab") as f:
        f.write(b'{"b":2}\n')

    w = Writer()
    rep = collect_source("t", arts, chats, w)
    assert rep.grown == ["sessions/a.jsonl"]
    assert (chats / "sessions" / "a.jsonl").read_bytes() == b'{"a":1}\n{"b":2}\n'
    assert not (chats / "revisions").exists()          # 纯追加:不产生 revision

    e = load(chats)["sessions/a.jsonl"]
    assert e.sha256 == digest_file(src).sha256
    assert e.supersedes == ""
    assert e.source_path == str(src)


def test_copy_preserved_on_rewrite(tmp_path):
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    arts = [_copy("sessions/a.jsonl", src)]
    collect_source("t", arts, chats, Writer())
    old_sha = load(chats)["sessions/a.jsonl"].sha256

    src.write_bytes(b'{"totally":"different"}\n')      # 非追加重写,前缀 sha 对不上

    w = Writer()
    rep = collect_source("t", arts, chats, w)
    rev = f"revisions/sessions__a.jsonl.{old_sha[:8]}.jsonl"
    assert rep.preserved == [("sessions/a.jsonl", rev)]

    assert (chats / rev).read_bytes() == b'{"a":1}\n'  # 旧证据进了不可变 revision
    assert (chats / "sessions" / "a.jsonl").read_bytes() == b'{"totally":"different"}\n'

    entries = load(chats)
    old = entries[rev]
    assert old.source_gone is True
    assert old.source_path == ""
    assert old.superseded_by == "sessions/a.jsonl"
    assert old.sha256 == old_sha
    assert entries["sessions/a.jsonl"].supersedes == rev


def test_gone_marks_source_gone_keeps_file(tmp_path):
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    collect_source("t", [_copy("sessions/a.jsonl", src)], chats, Writer())

    rep = collect_source("t", [], chats, Writer())     # 源侧没了
    assert rep.gone == ["sessions/a.jsonl"]
    assert (chats / "sessions" / "a.jsonl").exists()   # 一个字节都不动
    assert load(chats)["sessions/a.jsonl"].source_gone is True


def test_revision_entry_not_reported_gone_again(tmp_path):
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    collect_source("t", [_copy("sessions/a.jsonl", src)], chats, Writer())
    old_sha = load(chats)["sessions/a.jsonl"].sha256
    src.write_bytes(b'{"totally":"different"}\n')
    collect_source("t", [_copy("sessions/a.jsonl", src)], chats, Writer())
    rev = f"revisions/sessions__a.jsonl.{old_sha[:8]}.jsonl"

    rep = collect_source("t", [], chats, Writer())
    assert "sessions/a.jsonl" in rep.gone
    assert rev not in rep.gone                         # revision 本就是 gone,不再重复报


def test_dry_run_writes_nothing_report_matches_real(tmp_path):
    src = _make_src(tmp_path, b'{"a":1}\n')
    arts = [_copy("sessions/a.jsonl", src)]

    real = collect_source("t", arts, tmp_path / "chats_real", Writer())
    dry = collect_source("t", arts, tmp_path / "chats_dry", Writer(dry_run=True))

    assert real == dry                                 # report 与真跑一致
    assert not (tmp_path / "chats_dry").exists()       # 一个字节都不落盘


def test_dry_run_preserved_report_matches_real(tmp_path):
    """preserved 的 dry-run:同样的报告,但盘上旧证据原地不动。"""
    src = _make_src(tmp_path, b'{"a":1}\n')
    arts = [_copy("sessions/a.jsonl", src)]
    collect_source("t", arts, tmp_path / "chats", Writer())

    src.write_bytes(b'{"totally":"different"}\n')

    real = collect_source("t", arts, tmp_path / "chats2", Writer())
    dry = collect_source("t", arts, tmp_path / "chats3", Writer(dry_run=True))
    assert real == dry
    assert not (tmp_path / "chats3").exists()


def test_verify_bypasses_fast_path(tmp_path, monkeypatch):
    """verify=True 时快路径被绕过,digest_file 真的被调了。"""
    from hub.chats import collect as c

    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    arts = [_copy("sessions/a.jsonl", src)]
    collect_source("t", arts, chats, Writer())

    calls = []
    real = c.digest_file
    monkeypatch.setattr(c, "digest_file", lambda p: (calls.append(p), real(p))[1])

    collect_source("t", arts, chats, Writer())         # 不 verify:快路径命中
    assert calls == []

    # verify:两边都重算——金库里那份(证据本身对不对得上台账)和源那份(内容变没变)。
    # 日常只查金库那份存不存在;verify 才是"别信便宜提示,重新证一遍"的档位。
    collect_source("t", arts, chats, Writer(), verify=True)
    assert len(calls) == 2
    assert calls[0] == chats / "sessions/a.jsonl"       # 先验金库那份
    assert calls[1] == src


def test_missing_vault_copy_is_restored_even_when_source_unchanged(tmp_path):
    """金库里那份没了 → 照源重写。

    这是快路径最危险的盲区:它只比**源**的 (size, mtime),源一个字节没动,于是每次
    收集都报 unchanged —— 而金库那份(唯一事实源)其实已经不在了,系统永远发现不了。
    """
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    arts = [_copy("sessions/a.jsonl", src)]
    collect_source("t", arts, chats, Writer())

    vault_copy = chats / "sessions/a.jsonl"
    vault_copy.unlink()                       # 误删/同步工具清掉/磁盘坏

    rep = collect_source("t", arts, chats, Writer())   # 源一个字节没动
    assert rep.restored == ["sessions/a.jsonl"]
    assert rep.unchanged == []
    assert vault_copy.read_bytes() == b'{"a":1}\n'


def test_verify_catches_corrupted_vault_copy(tmp_path):
    """金库那份内容被改坏 → 只有 verify 查得出来(日常只查存在性,不付几百 MB 的读)。"""
    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    arts = [_copy("sessions/a.jsonl", src)]
    collect_source("t", arts, chats, Writer())

    vault_copy = chats / "sessions/a.jsonl"
    vault_copy.write_bytes(b'{"corrupted":true}\n')    # 字节坏了,但文件还在

    assert collect_source("t", arts, chats, Writer()).unchanged == ["sessions/a.jsonl"]
    assert vault_copy.read_bytes() == b'{"corrupted":true}\n'   # 日常查不出来,如实承认

    rep = collect_source("t", arts, chats, Writer(), verify=True)
    assert rep.restored == ["sessions/a.jsonl"]
    assert vault_copy.read_bytes() == b'{"a":1}\n'


def test_generated_sha_change_keeps_revision(tmp_path):
    payload1 = b'{"v":1}\n'
    payload2 = b'{"v":2}\n'
    chats = tmp_path / "chats"

    rep1 = collect_source("t", [_generated("sessions/g.jsonl", payload1)], chats, Writer())
    assert rep1.new == ["sessions/g.jsonl"]
    old_sha = load(chats)["sessions/g.jsonl"].sha256

    rep2 = collect_source("t", [_generated("sessions/g.jsonl", payload2)], chats, Writer())
    rev = f"revisions/sessions__g.jsonl.{old_sha[:8]}.jsonl"
    assert rep2.preserved == [("sessions/g.jsonl", rev)]
    assert (chats / rev).read_bytes() == payload1      # 旧快照留了 revision
    assert (chats / "sessions" / "g.jsonl").read_bytes() == payload2

    w3 = Writer()
    rep3 = collect_source("t", [_generated("sessions/g.jsonl", payload2)], chats, w3)
    assert rep3.unchanged == ["sessions/g.jsonl"]
    assert w3.written == []                            # 幂等对 GENERATED 同样成立


def test_generated_unchanged_writes_nothing(tmp_path):
    payload = b'{"v":1}\n'
    chats = tmp_path / "chats"
    collect_source("t", [_generated("sessions/g.jsonl", payload)], chats, Writer())
    w = Writer()
    rep = collect_source("t", [_generated("sessions/g.jsonl", payload)], chats, w)
    assert rep.unchanged == ["sessions/g.jsonl"]
    assert w.written == []


def test_manifest_written_last_on_midwrite_failure(tmp_path, monkeypatch):
    """落盘中途抛错 → manifest 没被更新(台账停在旧版本,下次重跑收敛)。"""
    from hub import writer as writer_mod

    src = _make_src(tmp_path, b'{"a":1}\n')
    chats = tmp_path / "chats"
    arts = [_copy("sessions/a.jsonl", src)]
    collect_source("t", arts, chats, Writer())
    baseline = (chats / "manifest.toml").read_text(encoding="utf-8")

    src.write_bytes(b'{"totally":"different"}\n')      # 逼进 preserved

    def boom(self, s, d):
        raise OSError("disk blew up")

    monkeypatch.setattr(writer_mod.Writer, "copy_binary", boom)
    with pytest.raises(OSError):
        collect_source("t", arts, chats, Writer())

    assert (chats / "manifest.toml").read_text(encoding="utf-8") == baseline
