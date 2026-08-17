"""原始对话证据的摘要原语。

为什么独立成顶层模块放 writer 之外:writer.py 是核心层,不能反向依赖 chats 包;
而摘要要在"边拷边算"里同步算,是 writer 和 chats 收集都要用的原语。放顶层,两边
都依赖它,方向不形成环。
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 1 << 20


class SourceChangedWhileCopying(Exception):
    """复制过程中源文件被改写(重试一次后仍变)。

    上游证据仍在被工具追加,此刻落盘签进台账的 sha 会跟实际字节对不上 —— 宁可失败
    让收集重跑,也不把半路上的证据当成定稿。
    """


@dataclass
class Digest:
    bytes: int
    sha256: str      # 小写 hex
    lines: int


def _count_lines(data: bytes) -> int:
    """按 b"\\n" 数行;非空且不以换行结尾时,最后那截也算一行。

    只看换行符、不做换行归一 —— 证据层的行数是"有几个物理行",不是"解析出几条记录"。
    """
    n = data.count(b"\n")
    if data and not data.endswith(b"\n"):
        n += 1
    return n


def digest_bytes(data: bytes) -> Digest:
    return Digest(len(data), hashlib.sha256(data).hexdigest(), _count_lines(data))


def digest_file(path: Path) -> Digest:
    """分块(1 MiB)读整个文件算摘要,不为记账把 678 MB 全读进内存。"""
    h = hashlib.sha256()
    size = 0
    nl = 0
    last = None
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
            size += len(chunk)
            nl += chunk.count(b"\n")
            last = chunk[-1]
    if last is not None and last != 0x0A:
        nl += 1
    return Digest(size, h.hexdigest(), nl)


def prefix_sha256(path: Path, n: int) -> str:
    """只读前 n 字节算 sha256,当作"纯追加"增长证明(§5.2)。n 超过文件长度抛 ValueError。"""
    total = path.stat().st_size
    if n > total:
        raise ValueError(f"n={n} 超过文件长度 {total}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        remaining = n
        while remaining > 0:
            chunk = f.read(min(_CHUNK, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


def copy_and_digest(fsrc, fdst, chunk: int = _CHUNK) -> Digest:
    """边拷边算,返回**实际写入 fdst** 的摘要 —— 不是事后重读 fdst,也不是对源算。

    这就是评审那条 bug 的修法:调用方"先 hash 源再 copy"之间源还在被追加,记下的
    sha 根本不是落盘字节;改成对"已经写进去的那些"算,台账才可信。
    """
    h = hashlib.sha256()
    size = 0
    nl = 0
    last = None
    while True:
        data = fsrc.read(chunk)
        if not data:
            break
        fdst.write(data)
        h.update(data)
        size += len(data)
        nl += data.count(b"\n")
        last = data[-1]
    if size and last != 0x0A:
        nl += 1
    return Digest(size, h.hexdigest(), nl)
