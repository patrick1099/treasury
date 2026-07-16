"""金库的唯一写入口。

**所有**写/删都必须走这里。--dry-run 的闸设在这一层,不设在调用方——
配置式预览的失败模式是"照真实的写"(最危险的方向);闸在写函数里的失败模式是
"什么都不写"。这条是 2026-07-12 用一次真实事故换来的。
"""
import io
import os
import shutil
import tarfile
from pathlib import Path

from hub.guard import check_source, has_denied_component, is_denied
from hub import fslink        # fslink 只依赖 stdlib，无循环导入

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
