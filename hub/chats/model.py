"""原始对话库的数据形状。

**这个文件是并行开发时的共享接口，由主聊独占维护。** 各源提取器 / manifest / 收集编排
都只读它，不改它——六个任务同时开工时，谁都往这里加字段就会互相覆盖。

两组分类，各自解决一个真问题:

- **kind = COPY / GENERATED** —— 决定"新旧关系怎么证明"(spec §5)。
  COPY 的源侧就是 append-only 的文件,能用**前缀 sha** 证明新内容是旧内容的超集;
  GENERATED 的源侧是数据库,我们导出的是快照,**没有前缀单调性**(一条 message 的 data
  在会话进行中会被就地更新),给不出任何增长证明。
- **role = TRANSCRIPT / AUXILIARY** —— 决定"索引层拿它干什么"(spec §4.1)。
  transcript 是对话正文,建 session + event;auxiliary 是辅助证据
  (`workspaces.toml` 的 hash→工程映射、`workspace.yaml`),同样 append-only 收进来,
  但**不建 session、不产 event**,只在补 session 元信息时被读。
  没有这条区分,索引层会为一张映射表建一个根本不存在的"会话"。
"""
from dataclasses import dataclass, field
from pathlib import Path

COPY = "copy"
GENERATED = "generated"

TRANSCRIPT = "transcript"
AUXILIARY = "auxiliary"


@dataclass
class Artifact:
    """一件要落进金库的证据。"""
    rel: str                        # 相对 <host>/<tool>/chats/ 的路径
    session_id: str = ""
    kind: str = COPY
    role: str = TRANSCRIPT
    src: Path | None = None         # COPY:源文件
    payload: bytes | None = None    # GENERATED:导出的字节
    lines: int = 0                  # GENERATED:导出了多少行(COPY 落盘时才数)
    meta: dict = field(default_factory=dict)    # 附进 manifest 的额外字段(值只能是 str/int/bool)


@dataclass
class Entry:
    """manifest.toml 里的一条:证据的身份,不是它的内容。

    `bytes`/`sha256`/`lines` 说的是**金库里这份实际落盘的字节**(由 `Writer.copy_binary`
    边拷边算得出),不是源文件的——"先 hash 源再 copy"那两步之间源还在被工具追加,
    拿源的摘要记账会跟落盘字节对不上(spec §6.1)。

    `source_*` 三个是**快路径**用的上次所见源 stat(spec §5.1):它们相同就跳过重新验证。
    这只是"快速未变提示",**不是内容等价证明**——`--verify` 是它的对冲。

    时间范围(首末消息时间)**故意不在这里**:那要解析正文才知道,而单次收集不该为了两个
    显示字段去解析几百 MB。它归索引层(索引本来就要逐行解析)。
    """
    rel: str
    source_path: str = ""
    role: str = TRANSCRIPT
    kind: str = COPY
    bytes: int = 0
    sha256: str = ""
    lines: int = 0
    source_size: int = 0
    source_mtime_ns: int = 0
    source_ino: int = 0         # 0 = 本平台/文件系统没给,别当成 0 号 inode
    imported_at: str = ""
    session_id: str = ""
    source_gone: bool = False
    superseded_by: str = ""     # 本条是旧证据时,指向取代它的 current
    supersedes: str = ""        # 本条是 current 时,指向被它取代的 revision
    meta: dict = field(default_factory=dict)


@dataclass
class SourceReport:
    source: str
    new: list[str] = field(default_factory=list)
    grown: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    preserved: list[tuple[str, str]] = field(default_factory=list)   # (rel, 旧证据另存路径)
    gone: list[str] = field(default_factory=list)                    # 源没了,金库这份留着
    restored: list[str] = field(default_factory=list)                # 金库那份没了/对不上,照源重写
    skipped: list[tuple[str, str]] = field(default_factory=list)     # (什么, 为什么)

    @property
    def wrote_anything(self) -> bool:
        return bool(self.new or self.grown or self.preserved or self.restored)


@dataclass
class ChatsReport:
    sources: dict[str, SourceReport] = field(default_factory=dict)
