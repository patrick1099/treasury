# ai-cli-migrate

换电脑时迁移 **Claude Code** 和 **Codex** 的全部个人数据。纯 Python 标准库,Windows 用 `py -3`,不装任何依赖。

```
ai-cli-migrate/
├── migrate.py          统一入口(一条命令同时处理两者)
├── claude_migrate.py   Claude Code: ~/.claude
├── codex_migrate.py    Codex: ~/.codex
├── pack_migration.py   一键打包(+ 打包.bat / 桌面快捷方式)
└── tests/              pytest(claude + codex)
```

## 统一入口(推荐)

```powershell
py -3 migrate.py status                     # 看本机装了哪个、多大
py -3 migrate.py export                      # 同时导出两者(默认存到 ai-cli-migrate 目录)
py -3 migrate.py export --out-dir D:\bak     # 指定输出目录
py -3 migrate.py export --include-logs        # Codex 连 logs 一起(默认不带)
py -3 migrate.py import --claude claude-backup-XXXX.zip --codex codex-backup-XXXX.zip
py -3 migrate.py import --claude <c.zip> --codex <x.zip> --remap-user dell alice  # 新机用户名不同,两者一起改
py -3 migrate.py import --claude <c.zip> --remap-path "C:\Users\dell\Desktop\proj" "D:\work\proj"  # 工程挪到别的文件夹
```

### 一键打包(换机傻瓜流程)

双击桌面快捷方式「一键打包迁移包」(或直接跑 `打包.bat` / `py -3 pack_migration.py`):
导出两者 + 工具源码 + 迁移说明,打成**一个** `ai-cli-迁移包-日期.zip` 放到桌面。
新机解压,照包里的 `迁移说明.md` 跑 `import` 即可。

导出得到两个包:`claude-backup-<时间戳>.zip`、`codex-backup-<时间戳>.zip`,默认就存在本工具目录(`ai-cli-migrate/`)下,已被 `.gitignore` 排除不会进仓库。两者都**不含登录凭证**,新机导入后各自重新 `/login`。

## 各迁了什么 / 不迁什么

| | Claude Code (`~/.claude`) | Codex (`~/.codex`) |
|---|---|---|
| 聊天记录 | `projects/*.jsonl`(全量) | `sessions/`(按日期) + `state_*.sqlite` |
| 记忆 | `projects/.../memory/` | `memories/` |
| 技能/插件 | `skills/` + `plugins/`(清单+marketplaces) | `skills/` + `plugins/` |
| 配置 | `settings.json` + `.claude.json` 的 `mcpServers` | `config.toml` |
| **不迁(凭证)** | `.credentials.json`、oauth | `auth.json`、`.sandbox-secrets` |
| **不迁(可重建)** | cache/telemetry/shell-snapshots… | cache/`.tmp`/`.sandbox*`/`cap_sid`/`installation_id` |

## 关键设计

- **SQLite 一致性快照**:Codex 的 `*.sqlite` 都是 WAL 模式的活跃库,直接裸拷 `.sqlite`+`-wal`+`-shm` 可能拷出撕裂快照而损坏。本工具用 SQLite `backup` API 生成一致性单文件快照(自动合并 WAL),**Codex 开着也能安全导出**,且不再拷 `-wal`/`-shm`。
- **logs 默认不迁**:`logs_*.sqlite` 是几百 MB 的 telemetry 日志、非聊天记录,默认排除,`--include-logs` 才打包。
- **导入前自动备份**:Claude 备份到 `~/.claude/backups/`;Codex 把旧 `~/.codex` 整体改名为 `.codex.backup-<时间戳>`。
- **用户名改写(两者都支持)**:新机用户名不同时用 `--remap-user OLD NEW`。
  - Claude:改写聊天记录目录名(按绝对路径编码)+ jsonl 内路径。
  - Codex:改写 `sessions/` 文本文件,以及 `*.sqlite` 里 `rollout_path`/`cwd`/`agent_path` 等**文本列**(走 SQL `UPDATE...REPLACE`,不是裸字节替换——后者会撑坏 SQLite 记录导致损坏)。Codex 的 `rollout_path` 是绝对路径,用户名变了不 remap 就找不到会话文件,所以这步是必要的。
  - 两者都只改 `Users<分隔符>用户名<分隔符>` 形态,不误伤同名词,也不碰非 Users 路径(如 D 盘项目)。
- **工程路径搬迁(仅 Claude)**:用 `--remap-path OLD_PATH NEW_PATH`。Claude 的聊天记录/记忆
  目录是按**工程绝对路径**编码命名的(`[^A-Za-z0-9]→-`),工程挪到别的文件夹后,新路径下
  Claude 找不到旧历史;此参数把编码目录改名(含该工程的 worktree 子目录)并改写其中的旧路径。
  Codex 历史不按路径归档,挪文件夹不影响关联,故不需要(其 cwd 字段改写见 `TODO.md`)。

## 单独使用某一个

```powershell
py -3 claude_migrate.py export                 # 还支持 git-init 把 ~/.claude 变 git 仓库
py -3 codex_migrate.py export --out codex.zip   # 还支持 inspect 看清单
```

## 测试

```powershell
py -3 -m pytest -q          # claude + codex 两套
```

## 安全提示

两个包都**未加密**,含私密聊天记录、记忆、本机路径等,当作私有数据妥善保管。
