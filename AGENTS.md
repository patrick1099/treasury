# treasury

## 先读
1. docs/HANDOFF.md —— 现在做到哪了（没有这个文件 = 没有进行中的工作）
2. docs/BLUEPRINT.md —— 它是什么、行为契约
3. docs/CHANGELOG.md —— 最近 5 条；要改哪块，再搜那块相关的「没选的路」
4. 改金库格式前读 `hub/schema_md.py`（生成 SCHEMA.md，是 hub 与各平台之间的唯一契约）；命令用法看 `hub/README.md`；需求全貌看 `docs/NEEDS.md`

## 命令
- 跑：`py -3 -m hub.cli <命令> --vault C:/Users/huawei/treasury-vault --host 2025-bg-016`（`--json` 出机器信封，`--dry-run` 只预演）
- 测：`py -3 -m pytest tests -q -p no:cacheprovider`（全量约 3.5 分钟）
- 插件发版后刷新：`py -3 -m hub.cli sync --vault C:/Users/huawei/treasury-vault --host 2025-bg-016 --refresh -m "<为什么>"`

## 代码地图（改哪类东西去哪）
| 要改的 | 去哪 |
|---|---|
| 加 / 去掉一个 AI 平台 | `hub/platforms/__init__.py` 的 `REGISTRY` 加删一行 + 同目录一个适配器；别处不许写平台名单或按平台名分支（`tests/hub/test_platforms.py` 会拦） |
| 某个平台的具体行为（视图接线、链接落点、inventory 单元格、toggle） | 该平台的适配器 `hub/platforms/<平台>.py`；claude / codex 共有部分在 `_cli.py` |
| 本机启用哪些平台 | 金库 `<host>/device.toml` 顶层 `platforms` |
| 命令入口、参数、JSON 输出 | `hub/cli.py`（错误码映射在 `hub/cliout.py`） |
| 金库格式、device.toml 字段、scope 语法 | `hub/schema_md.py` |
| 任何写盘 | 一律经 `hub/writer.py` 的 `Writer`（dry-run 闸在里面） |
| 插件 CLI 装卸 | `hub/plugin_ops.py` + `hub/plugin_cli.py`（按适配器声明的 `cli_dialect` 分支） |

## 坑
- **Esafenet 透明加密**：`.py` 在盘上是密文。读写用 Claude 的 Read/Edit/Write 或 `py -3`，Bash 的 `cat` / `grep` / `head` 看到的是密文，PowerShell 写入会落成明文。
- Bash 工具里用多行 heredoc 喂 python 脚本常出现引号解析失败；长脚本先写进 scratchpad 的 `.py` 文件，再用 `py -3` 跑。
- 控制台是 GBK，直接 print 中文可能报 UnicodeEncodeError 或乱码；看输出时重定向到文件，或 `.encode('ascii','backslashreplace')`。
- 金库根的 `SCHEMA.md` 是派生物，目前和 `hub/schema_md.py` 已经不一致；只有 scaffold 会重写它。
- `hub_gui/` 是没进 git 的 GUI 草稿，`web/app.js` 里写死了四个平台名；要用它，得先改成读 inventory 顶层的 `harnesses`。
- 金库里常有别的会话没提交的改动（如 `shared/skills/script-manager/`）；提交时只 add 自己改的文件。
