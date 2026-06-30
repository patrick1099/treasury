#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包迁移包:导出 Claude Code + Codex 聊天记录,连同工具源码和迁移说明,
打成一个自包含 zip 放到桌面。换电脑时把这个 zip 拷过去,解压即可直接安装。

供桌面快捷方式(打包.bat)双击调用,也可单独运行:
  py -3 pack_migration.py
  py -3 pack_migration.py --out-dir D:\\some\\dir   # 改放别处,默认放桌面
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()

# 打进迁移包的工具源码(claude/codex 子工具 + 统一入口 + 自身说明)
TOOL_FILES = [
    "migrate.py",
    "claude_migrate.py",
    "codex_migrate.py",
    "README.md",
]


def find_desktop():
    """返回桌面目录;兼容 OneDrive 重定向。"""
    for candidate in (HOME / "Desktop", HOME / "OneDrive" / "Desktop"):
        if candidate.exists():
            return candidate
    return HOME / "Desktop"


def write_install_guide(dest):
    """写一份面向新电脑的安装/迁移说明到包内。"""
    guide = """# 迁移说明(新电脑上照这个做)

这个包是用 `ai-cli-migrate` 工具从旧电脑导出的,里面有 **Claude Code + Codex 的全部
个人数据**(聊天记录、memory、skills、plugins、MCP 配置等),以及工具源码本身。

> 不含登录凭证 —— 新机装好后两边都要重新 `/login`。

## 目录结构

```
ai-cli-迁移包-日期/
├── 迁移说明.md          <- 你正在看的这份
├── tool/                <- 迁移工具源码(纯 Python 标准库)
│   ├── migrate.py       <- 统一入口
│   ├── claude_migrate.py
│   ├── codex_migrate.py
│   └── README.md
└── data/                <- 导出的数据
    ├── claude-backup-<时间戳>.zip
    └── codex-backup-<时间戳>.zip
```

## 新电脑上安装(三步)

前提:新机已装好 Python(`py -3` 可用)、Claude Code、Codex。

1. 解压本包到任意目录,打开终端 `cd` 进 `tool/`。

2. 先看一眼要导入什么:
   ```
   py -3 migrate.py status
   ```

3. 导入(把下面的文件名换成 data/ 里实际的 zip 名):
   ```
   py -3 migrate.py import --claude ..\\data\\claude-backup-XXXX.zip --codex ..\\data\\codex-backup-XXXX.zip
   ```

   **如果新电脑用户名和旧机不同**(比如旧机是 dell,新机是 alice),加 `--remap-user`:
   ```
   py -3 migrate.py import --claude ..\\data\\claude-backup-XXXX.zip --codex ..\\data\\codex-backup-XXXX.zip --remap-user dell alice
   ```
   它会改写会话目录名、jsonl 里的路径、以及 Codex sqlite 里的路径列。

4. 打开 Claude Code 和 Codex,各自 `/login` 重新登录。完事。

## 单独只导一个

```
py -3 migrate.py import --claude ..\\data\\claude-backup-XXXX.zip    # 只导 Claude
py -3 migrate.py import --codex  ..\\data\\codex-backup-XXXX.zip     # 只导 Codex
```

更多用法见 `tool/README.md`。
"""
    (dest / "迁移说明.md").write_text(guide, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="一键打包 Claude/Codex 迁移包到桌面")
    ap.add_argument("--out-dir", help="迁移包输出目录,默认桌面")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve() if args.out_dir else find_desktop()
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    bundle_name = f"ai-cli-迁移包-{ts}"

    print("=" * 56)
    print(f"  一键打包迁移包  ({ts})")
    print("=" * 56)

    with tempfile.TemporaryDirectory(prefix="ai-cli-pack-") as tmp:
        staging = Path(tmp) / bundle_name
        tool_dir = staging / "tool"
        data_dir = staging / "data"
        tool_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        # 1) 导出数据 —— 复用现有 migrate.py export(默认范围:含全量聊天记录/memory,
        #    不含几百 MB 运行日志,不含登录凭证)
        print("\n[1/4] 导出 Claude + Codex 数据...")
        rc = subprocess.run(
            [sys.executable, str(HERE / "migrate.py"),
             "export", "--out-dir", str(data_dir)],
        ).returncode
        # 任一子导出失败就硬停 —— 绝不把残缺数据打进迁移包(否则换机时静默丢数据)。
        if rc != 0:
            print(f"\nERROR: 导出失败(退出码 {rc}),已中止打包,不生成迁移包。",
                  file=sys.stderr)
            print("      请把上面的报错发我,修好再打包。", file=sys.stderr)
            return rc
        backups = list(data_dir.glob("*.zip"))
        if not backups:
            print("\nERROR: 没有导出任何数据,中止打包。", file=sys.stderr)
            return 1

        # 2) 放工具源码
        print("\n[2/4] 收集工具源码...")
        for name in TOOL_FILES:
            src = HERE / name
            if src.exists():
                shutil.copy2(src, tool_dir / name)
                print(f"    + tool/{name}")
            else:
                print(f"    (跳过缺失文件 {name})")

        # 3) 写迁移说明
        print("\n[3/4] 写迁移说明...")
        write_install_guide(staging)
        print("    + 迁移说明.md")

        # 4) 打成一个 zip
        print("\n[4/4] 打包...")
        zip_path = out_dir / f"{bundle_name}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(
            zip_path, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False
        ) as zf:
            for f in staging.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(staging.parent))

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print("\n" + "=" * 56)
    print("  完成!")
    print(f"  迁移包: {zip_path}")
    print(f"  大小:   {size_mb:.1f} MB")
    print("  含: tool/ 工具源码 + data/ 聊天记录 + 迁移说明.md")
    print("  不含登录凭证,新机导入后各自 /login。")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
