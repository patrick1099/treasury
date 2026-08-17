"""原始对话库的 append-only 状态机:每个 artifact 每次收集只落四态之一。

spec §5。四态:

    内容相同                   → unchanged   零写入
    能证明新内容包含全部旧证据   → grown       覆盖 current
    不能证明                   → preserved   旧的存成不可变 revision,新的写进 current
    源侧没了                   → gone        一个字节都不动,标 source_gone

**"能不能证明"按源的性质分,不是设计缺陷**——不同源能给出的证明强度本来就不同:

- **COPY**(claude/codex/copilot-* 那些 append 出来的 jsonl)有**前缀 sha** 这个增长
  证明:新 size > 旧 size 且 sha256(新文件前 旧size 字节) == 旧 sha → 新内容是旧内容
  的超集,可以放心覆盖 current(spec §5.2)。
- **GENERATED**(opencode 从 SQLite 导出的快照)**没有前缀单调性**:一条 message 的
  data 在会话进行中会被就地更新。v1 曾用「新 lines >= 旧 lines」判增长——那条不成立:
  行数相同可能是就地更新,行数增加也可能同时删了旧行。照它覆盖会把已经采集到的旧值
  弄丢,而"旧证据不丢"正是本层存在的理由。所以 GENERATED 的 sha 一变,**一律走
  preserved**(spec §5.3)。opencode 只有 103 个会话、总量远小于 Codex,版本噪音是
  可以承受的代价。

**日常快路径**(spec §5.1):(源 size, 源 mtime_ns) 与 manifest 相同 → 连 sha 都不算,
直接 unchanged。它是"快速未变提示",不是内容等价证明——678 MB 每次全 hash 不可接受,
这是有意识买下的风险。`--verify` 跳过快路径、全量重算,是它的对冲。

**manifest 最后写**(spec §6.1):所有 artifact 处理完才写台账。台账不能领先于事实——
中途炸了的话,宁可台账停在旧版本(下次重跑收敛),也不能记着一件其实没落盘的事。
"""
import datetime
from pathlib import Path

from hub.digest import Digest, digest_bytes, digest_file, prefix_sha256
from hub.writer import Writer
from hub.chats.manifest import dump, load
from hub.chats.model import Artifact, COPY, GENERATED, Entry, SourceReport


def _now_iso() -> str:
    """UTC ISO8601 秒精度。测试只断言存在且可解析,不断言具体时刻。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _revision_rel(rel: str, sha256: str) -> str:
    """preserved 时旧证据的 manifest rel:原 rel 打平(/→__) + 旧 sha 前 8 位 + 原后缀。

    放进 revisions/ 下。sha 前缀让同名 artifact 的不同版本不会撞同一个 revision 名;
    后缀保留让人一眼认出原类型(spec §5.4)。rename 撞名会抛,所以这名字必须是唯一的。
    """
    suffix = Path(rel).suffix
    return f"revisions/{rel.replace('/', '__')}.{sha256[:8]}{suffix}"


def _vault_copy_ok(current: Path, old: Entry, verify: bool, w: Writer) -> bool:
    """金库里那份还在不在、(verify 时)对不对得上台账。

    为什么非查不可:快路径只比**源**的 (size, mtime),金库那份被误删、被同步工具清掉、
    或磁盘坏掉,它一概看不见 —— 台账继续记着"有",每次收集继续报 unchanged,而这一层
    的全部意义就是"唯一事实源不能丢"。存在性检查只花一次 stat,便宜到没有不做的理由。

    内容校验只在 `--verify` 下做:那才是"别信便宜提示,重新证一遍"的档位,日常不该为它
    付几百 MB 的读。

    dry-run 下永远返回 True:dry-run 不落盘,一路判"要重写"只会产出一份假的待办清单。
    """
    if w.dry_run:
        return True
    if not current.exists():
        return False
    if verify:
        return digest_file(current).sha256 == old.sha256
    return True


def _digest(art: Artifact, current: Path, w: Writer) -> Digest:
    """把 art 的内容写进 current,返回**实际落盘字节**的摘要(dry-run 对源直接算)。

    COPY 走 copy_binary(原子写 + 边拷边算,sha 天然是金库里那份的);GENERATED 走
    write_bytes。dry-run 下两个原语都不落盘、返回 None,这时对源/内存载荷直接算摘要,
    保证 dry-run 的 report 与真跑一致。
    """
    if art.kind == COPY:
        d = w.copy_binary(art.src, current)
        return d if d is not None else digest_file(art.src)
    d = w.write_bytes(current, art.payload)
    return d if d is not None else digest_bytes(art.payload)


def _entry_for(art: Artifact, d: Digest, st, supersedes: str = "") -> Entry:
    return Entry(
        rel=art.rel,
        source_path=str(art.src) if art.src else "",
        role=art.role,
        kind=art.kind,
        bytes=d.bytes,
        sha256=d.sha256,
        lines=d.lines,
        source_size=st.st_size if st else 0,
        source_mtime_ns=st.st_mtime_ns if st else 0,
        source_ino=st.st_ino if st else 0,
        imported_at=_now_iso(),
        session_id=art.session_id,
        supersedes=supersedes,
        meta=dict(art.meta),
    )


def _preserve(report, entries, chats_dir, rel, art, old, current, w, st) -> None:
    """旧证据改名进 revisions/,新的写进 current;旧条目改挂到 revision 名下。

    顺序不能反:rename 先把旧 current 挪走(copy_binary 的 os.replace 会原子覆盖,
    直接写会把唯一一份旧证据毁掉),再写新的。dest 已存在时 rename 抛——绝不覆盖。
    旧条目保留 bytes/sha256(它是这版证据的全部身份),source_path 留空、source_gone
    置真:它不再对应任何源文件,只是"曾经存在过这份证据"的记录。
    """
    rev = _revision_rel(rel, old.sha256)
    rev_path = Path(chats_dir) / rev
    w.rename(current, rev_path)
    d = _digest(art, current, w)
    entries[rev] = Entry(
        rel=rev, source_path="", role=old.role, kind=old.kind,
        bytes=old.bytes, sha256=old.sha256, lines=old.lines,
        source_size=0, source_mtime_ns=0, source_ino=0,
        imported_at=old.imported_at, session_id=old.session_id,
        source_gone=True, superseded_by=rel, meta=dict(old.meta),
    )
    entries[rel] = _entry_for(art, d, st, supersedes=rev)
    report.preserved.append((rel, rev))


def collect_source(source: str, arts: list[Artifact], chats_dir: Path,
                   w: Writer, verify: bool = False) -> SourceReport:
    report = SourceReport(source=source)
    entries = load(chats_dir)
    seen: set[str] = set()
    dirty = False

    for art in arts:
        rel = art.rel
        seen.add(rel)
        current = Path(chats_dir) / rel
        old = entries.get(rel)
        st = art.src.stat() if art.src else None

        if old is None:
            d = _digest(art, current, w)
            entries[rel] = _entry_for(art, d, st)
            report.new.append(rel)
            dirty = True
            continue

        if not _vault_copy_ok(current, old, verify, w):
            # 金库里那份没了/对不上台账。台账记着有,盘上却没有——快路径只比源的
            # stat,永远看不见这件事,于是每次收集都报 unchanged,唯一事实源丢了系统
            # 却发现不了。照源重写一份,当作这一版证据重新落盘。
            d = _digest(art, current, w)
            entries[rel] = _entry_for(art, d, st, supersedes=old.supersedes)
            report.restored.append(rel)
            dirty = True
            continue

        if art.kind == COPY:
            if not verify and st is not None and \
               (st.st_size, st.st_mtime_ns) == (old.source_size, old.source_mtime_ns):
                report.unchanged.append(rel)
                continue
            d = digest_file(art.src)
            if d.sha256 == old.sha256:
                report.unchanged.append(rel)
                if (st.st_size, st.st_mtime_ns) != (old.source_size, old.source_mtime_ns):
                    # stat 变了但内容没变:把新 stat 写回,否则下次还白算
                    old.source_size = st.st_size
                    old.source_mtime_ns = st.st_mtime_ns
                    old.source_ino = st.st_ino
                    dirty = True
                continue
            if st.st_size > old.bytes and \
               prefix_sha256(art.src, old.bytes) == old.sha256:
                d = _digest(art, current, w)
                entries[rel] = _entry_for(art, d, st, supersedes=old.supersedes)
                report.grown.append(rel)
                dirty = True
                continue
            _preserve(report, entries, chats_dir, rel, art, old, current, w, st)
            dirty = True
            continue

        # GENERATED:没有增长证明,sha 一变一律 preserved(v1 的行数判据已作废)
        if digest_bytes(art.payload).sha256 == old.sha256:
            report.unchanged.append(rel)
            continue
        _preserve(report, entries, chats_dir, rel, art, old, current, w, st)
        dirty = True

    for rel, entry in entries.items():
        # revision 条目本就 source_gone=True,不重复报 gone
        if rel not in seen and not entry.source_gone:
            entry.source_gone = True
            report.gone.append(rel)
            dirty = True

    if dirty:
        w.write_text(Path(chats_dir) / "manifest.toml", dump(entries))
    return report
