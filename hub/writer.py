"""金库的唯一写入口。

**所有**写/删都必须走这里。--dry-run 的闸设在这一层,不设在调用方——
配置式预览的失败模式是"照真实的写"(最危险的方向);闸在写函数里的失败模式是
"什么都不写"。这条是 2026-07-12 用一次真实事故换来的。
"""
import io
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from hub.guard import check_source, has_denied_component, is_denied
from hub import fslink        # fslink 只依赖 stdlib，无循环导入
from hub.digest import Digest, SourceChangedWhileCopying, copy_and_digest, digest_bytes

class Writer:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.written: list[Path] = []
        self.removed: list[Path] = []

    def copy_file(self, src: Path, dest: Path) -> None:
        """把**单个源文件**拷进金库。硬闸(check_source)长在这里面。

        为什么非有这个原语不可:`write_text()` 收到的是**已经读出来的文本**,它永远
        看不见源路径,所以硬闸没法长在它里面 —— 调用方只能自己记得先 check_source()。
        "闸设在调用点、不设在原语里"这个形状,本项目已经因此出过**四次**事故;
        最近一次的复现只需要一行:把 collect/__init__.py 里那句 check_source(p) 删掉,
        一个 secrets/CLAUDE.md 就原样泄进金库。

        跟 snapshot_repo() 一样,调用方那道 check_source **留着不动**(纵深防御:
        它拦得更早、报错更能说清是流水线里哪个条目被拒)。这里是最后一道:
        万一未来某个新调用方忘了挡,失败方向是"什么都不写",不是"照真的写"。

        闸拦的是**读**,所以它在 --dry-run 下同样生效(dry-run 的闸在 write_text 里面)。
        """
        src = Path(src)
        check_source(src)
        self.write_text(dest, src.read_text(encoding="utf-8"))

    def copy_binary(self, src: Path, dest: Path) -> Digest | None:
        """把源文件**字节级原样**拷进金库,返回实际落盘字节的摘要(dry-run 返回 None)。

        为什么不能用 copy_file 干这件事:它走 read_text() + write_text(),而 write_text
        **会沿用目标已有的换行风格重写**(见下)。对记忆/CLAUDE.md 那是对的(省掉整文件
        重写的 diff 噪音);对原始对话证据是错的:改了字节,金库这份 sha 就不再等于源的
        sha,append-only 幂等判据当场失效、每次收集都重写一遍;且整个文件读进内存(实测
        单会话最大 35 MB,Codex 总量 678 MB);遇到非法编码还直接抛,而证据库的承诺是
        "原样保存"不是"保存我们能解码的那部分"。所以这一层不做任何换行/编码处理。

        原子写的原因(§6.1,评审逮的真 bug):直接以 wb 打开目标,复制中途失败/断电就把
        唯一一份旧证据截断了。这里走同目录唯一临时文件 + copy_and_digest 边拷边算 +
        拷贝前后各 stat 一次源((size, mtime_ns) 变了说明源还在被追加,重试一次仍变就
        抛 SourceChangedWhileCopying)+ flush/fsync + os.replace 原子替换。摘要是对
        **实际写进去的字节**算的 —— "先 hash 源再 copy"那两步之间源还会被追加,台账
        sha 会跟落盘字节对不上。任何异常都在退出前清掉临时文件。

        dry-run 闸在写之前;check_source 拦的是**读**,因此在 dry-run 下同样生效。
        """
        src, dest = Path(src), Path(dest)
        check_source(src)
        self.written.append(dest)
        if self.dry_run:
            print(f"  [dry-run] {'改写' if dest.exists() else '新建'} {dest}  "
                  f"({src.stat().st_size} 字节)")
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):                    # 源被追加时重试一次,仍变才抛
            fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".",
                                            suffix=".hub-tmp")
            tmp = Path(tmp_name)
            try:
                before = src.stat()
                with open(src, "rb") as fsrc, os.fdopen(fd, "wb") as fdest:
                    digest = copy_and_digest(fsrc, fdest)
                    fdest.flush()
                    os.fsync(fdest.fileno())
                after = src.stat()
                if (after.st_size, after.st_mtime_ns) == (before.st_size,
                                                          before.st_mtime_ns):
                    os.replace(tmp, dest)     # 原子;失败则原文件不动
                    return digest
            except BaseException:             # 编码/fsync/replace 任何失败都清 temp
                tmp.unlink(missing_ok=True)
                raise
            tmp.unlink(missing_ok=True)       # 源变了,这轮临时作废,重开一轮
        raise SourceChangedWhileCopying(f"复制过程中源被改写:{src}")

    def rename(self, src: Path, dest: Path) -> None:
        """把证据文件改名/搬家(dest 已存在时抛,绝不覆盖)。

        preserved 把旧 current 挪进 revisions/ 时用。dest 已存在说明这个 revision 名
        已经被占——要么上次 crash 残留,要么 sha 前缀撞名;无论哪种,覆盖它都是把已经
        采集到的证据弄丢,宁可炸。dry-run 闸照旧:只记账、不动盘。
        """
        src, dest = Path(src), Path(dest)
        if dest.exists():
            raise FileExistsError(f"rename 拒绝覆盖已存在的目标:{dest}")
        self.written.append(dest)
        if self.dry_run:
            print(f"  [dry-run] 改名 {src} → {dest}")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dest)

    def write_bytes(self, path: Path, data: bytes) -> Digest | None:
        """字节级写;与 write_text 同形,但**不做任何换行/编码处理**(dry-run 返回 None)。

        给 GENERATED artifact(从 SQLite 导出的快照)落盘用:内容已经是我们生成的字节,
        再经 write_text 的换行归一/utf-8 编码就是画蛇添足——证据层的字节要原样进仓,
        幂等判据(两次导出字节相同)才成立。返回摘要,台账直接用它,不事后重读。
        """
        path = Path(path)
        self.written.append(path)
        if self.dry_run:
            print(f"  [dry-run] 字节写 {'改写' if path.exists() else '新建'} {path}  "
                  f"({len(data)} 字节)")
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return digest_bytes(data)

    def write_text(self, path: Path, text: str) -> None:
        path = Path(path)
        self.written.append(path)
        if self.dry_run:
            n = len(text.encode("utf-8"))
            print(f"  [dry-run] {'改写' if path.exists() else '新建'} {path}  ({n} 字节)")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        newline = "\n"
        if path.exists():
            # 沿用目标原有的换行风格：一律按 LF 写回会把仓库里的 CRLF 文件记成整文件重写。
            newline = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
        path.write_text(text, encoding="utf-8", newline=newline)

    def write_text_atomic(self, path: Path, text: str) -> None:
        """原子写：同目录**唯一**临时文件 + flush/fsync + os.replace，绝不留半截文件。

        视图 / 受管块 / 配置都走它——尤其 opencode.json 带明文密钥，截断代价高。
        临时名用 tempfile.mkstemp 生成唯一名（**不能用固定 .hub-tmp**：两次写同一 path 或
        上次崩溃残留会撞名互相覆盖）。**任何异常**（含编码错、fsync 失败）都在退出前清掉临时
        文件——不能只在 OSError 分支清。承诺只到单文件：跨文件一批写不是事务，中途失败可能
        部分完成，靠重跑收敛。
        """
        path = Path(path)
        self.written.append(path)
        if self.dry_run:
            n = len(text.encode("utf-8"))
            print(f"  [dry-run] 原子写 {'改写' if path.exists() else '新建'} {path}  ({n} 字节)")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        newline = "\r\n" if (path.exists() and b"\r\n" in path.read_bytes()) else "\n"
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".hub-tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)              # 原子；失败则原文件不动
        except BaseException:                  # 编码/fsync/replace 任何失败都清 temp
            tmp.unlink(missing_ok=True)
            raise

    def rmtree(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        self.removed.append(path)
        if self.dry_run:
            print(f"  [dry-run] 删除目录 {path}")
            return
        shutil.rmtree(path)

    def unlink(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        self.removed.append(path)
        if self.dry_run:
            print(f"  [dry-run] 删除 {path}")
            return
        path.unlink()

    def make_dir_link(self, target: Path, link: Path) -> None:
        link = Path(link)
        self.written.append(link)
        if self.dry_run:
            print(f"  [dry-run] 建链接 {link} → {target}")
            return
        fslink.make_dir_link(target, link)

    def remove_dir_link(self, link: Path) -> None:
        link = Path(link)
        if not os.path.lexists(link):
            return
        self.removed.append(link)
        if self.dry_run:
            print(f"  [dry-run] 删除链接 {link}")
            return
        fslink.remove_dir_link(link)

    def copy_tree(self, src: Path, dest: Path) -> None:
        """派生目录的全量重写:先清空 dest,再整棵拷过去。

        不做增量——派生目录的真源永远在别处,金库这份改了也白改。

        硬闸挡在这一层:树里任何一层命中 hub.guard.is_denied 的条目(secrets/、
        auth.json、.env,以及指向它们的符号链接/junction)一律跳过、不拷贝,
        同级的其余条目照常拷贝——不是整棵树报错中止。每个调用方(collect_skills、
        以后的 Task 9 等)都自动继承这层保护,不用各自记得挡。
        """
        self.rmtree(dest)
        if self.dry_run:
            print(f"  [dry-run] 拷贝 {src} → {dest}")
            self.written.append(Path(dest))
            return

        def _ignore(dirpath: str, names: list[str]) -> set[str]:
            return {name for name in names if is_denied(Path(dirpath) / name)}

        shutil.copytree(src, dest, ignore=_ignore)
        self.written.append(Path(dest))

    def extract_tar(self, dest: Path, tar_bytes: bytes) -> None:
        """快照的全量重写:先清空 dest,再把 tar 字节流整个解出去。

        不做增量——快照的真源永远在别处(某个 git 仓的 HEAD),金库这份改了也白改。
        filter="data" 是安全要求:拒绝归档里的绝对路径、`..` 穿越和逃逸目标目录的
        符号链接/硬链接。

        硬闸也挡在这一层,跟 copy_tree 同一个原则:归档里任何成员的**名字**
        (`TarInfo.name`,archive-internal 相对路径)命中 hub.guard.has_denied_component
        的一律跳过、不解出,同级的其余成员照常解——不是整包报错中止。用
        has_denied_component 而不是 is_denied:成员名不是文件系统路径,resolve()
        对它既无意义又依附 cwd(细节见 guard.py 里的文档)。

        指向被挡目标的符号链接不需要额外处理:被挡内容本身根本没有被解出到
        dest,任何指向它的符号链接(不管自己叫什么名字)解出来也只是一个悬空
        链接,没有真实字节流出;真正会泄漏字节的路径——链接目标逃出 dest 之外
        (比如指到宿主文件系统上真实的 secrets/)——已经由 filter="data" 挡住了。
        """
        dest = Path(dest)
        self.rmtree(dest)
        if self.dry_run:
            print(f"  [dry-run] 解包 → {dest}")
            self.written.append(dest)
            return
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
            members = [m for m in tf.getmembers() if not has_denied_component(m.name)]
            tf.extractall(dest, members=members, filter="data")
        self.written.append(dest)
