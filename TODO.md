# TODO

待办与后续想法。

## 跨项目"通用记忆"复用（暂缓，已设计未实现）

**背景**：Claude Code 的记忆按工程绝对路径存在 `~/.claude/projects/<编码路径>/memory/`，
没有"全局记忆"。所以通用类记忆（账号、插件、工作习惯偏好等）被困在某个具体工程下，
新开别的工程时不会自动带过去。

**已定方案**（待实现）：
- 新建 `~/.claude/_global_memory/` 作为通用记忆的唯一源。
- `memory_seed.py`：
  - `classify` —— 列出某项目记忆，分"通用 / 项目专属"。
  - `pull-global` —— 把标记为通用的从项目 memory 抽进 `_global_memory/`。
  - `seed --to <新项目 memory 目录>` —— 拷入 `_global_memory/*.md` 并幂等合并 MEMORY.md。
- 通用记忆的识别方式：在记忆 frontmatter 加 `metadata.scope: global`，工具按 scope 抓
  （倾向这个，自描述、不依赖外部名单）。

## Codex cwd 的路径搬迁改写（remap-path 的 Codex 侧）

`import --remap-path` 目前**只改 Claude**（Claude 历史/记忆按工程路径归档，挪文件夹会孤儿）。
Codex 历史不按路径归档，挪文件夹不影响关联，只是 session/sqlite 里的 `cwd` 字段仍显示旧路径
（纯外观）。后续可复用 `codex_migrate.py` 里的 `_remap_text_file` / `_remap_sqlite_paths`，
把整段旧路径→新路径也改一遍，让显示一致。

## 已知 bug（2026-07-06 真实换机实测发现，共 7 个，均未修复，靠手工修复绕过）

换机场景：旧机用户名 `dell` → 新机 `huawei`，工程文件夹同时也搬了（`dell` 下的中文路径 →
`huawei` 下的 `MyProjects\20260525-xinao` 路径），即 `--remap-user`+`--remap-path` 同时用。

1. **`--remap-user` + `--remap-path` 同用时，remap-path 静默 0 命中**。`claude_migrate.py`
   的 `cmd_import` 里 remap-user 先跑，把目录名 `dell`→`huawei` 改掉；remap-path 后跑，但它
   用**调用时传入的旧路径**（仍写着 `dell`）算 `encode_project_path(old)` 去匹配目录名——此时
   目录已经被上一步改名成 `huawei`，永远匹配不到，输出「目录改名 0 个，内容路径改写 0 个文件」
   且**不报错**。后果：聊天记录/记忆散落在"改了用户名但没改工程路径"的目录里，没有并入新工程
   目录。**修法建议**：`cmd_import` 里应该在 remap-user *之前*跑 remap-path，或者 remap-path
   匹配前先对旧路径本身也套一遍 remap-user 的替换再编码。

2. **`--remap-user` 不改 `settings.json`/`plugins/*.json` 里的路径，插件全挂**。只改了会话
   目录名 + jsonl 内路径，完全没碰 `~/.claude/settings.json` 的
   `extraKnownMarketplaces.*.source.path`、`~/.claude/plugins/known_marketplaces.json` 的
   `installLocation` 和嵌套 `source.path`（**两处都要改，容易漏一处**）、
   `~/.claude/plugins/installed_plugins.json` 的 `installPath`。换用户名后这几处全指向旧机
   路径，`/reload-plugins` 直接报错（本例 6 个插件全挂）。而且 `plugins/cache/` 本来就是"可
   重建、不迁移"范围，新机上目录都不存在，`installed_plugins.json` 光改路径字符串没用，只能
   清空 `plugins:{}` 再靠 `/plugin install` 重装。**修法建议**：`--remap-user`/`--remap-path`
   应该同时覆盖这三个 plugins 相关 json 文件的路径字段。

3. **Windows PowerShell 默认 GBK 控制台编码，`log()` 打印 `⚠` 直接 `UnicodeEncodeError` 崩溃**。
   `claude_migrate.py` 的 `log()` 是裸 `print()`，没有兜底编码。好在崩溃点在
   `backup_current()`/写文件*之前*，没写入/没备份就死，数据没受影响，但看起来像迁移彻底失败。
   **规避**：跑之前 `$env:PYTHONIOENCODING="utf-8"`。**修法建议**：`log()` 里
   `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`，或者干脆别用 ASCII 之外的
   字符（`⚠` 换成 `[!]`）。

4. **`codex_migrate.py` 导入时目标目录被占用，裸崩且状态不明**。`_backup_existing_profile()`
   用 `shutil.move(target_profile, backup_path)` 整体改名备份旧 `~/.codex`，如果里面有文件被
   其他进程占用（本例：VS Code 的 ChatGPT/Codex 插件还开着，锁住了 `goals_1.sqlite`），
   `shutil.move` → `rmtree` 部分文件删不掉，抛 `PermissionError`，import 直接终止，只留一堆
   raw traceback，没有回滚/清理提示。**修法建议**：`_backup_existing_profile` 应该先探测目标
   目录是否有锁（比如逐文件 try rename），失败时给出清晰提示（"检测到 X 被进程 Y 占用，请先
   关闭"），而不是让 shutil 的裸 traceback 冒出来。

5. **remap-user 改名后出现大小写不一致的目录名，根因未查**。同一批 worktree 目录里，
   `remap_user_projects()` 把一个目录正常改成大写开头 `C--Users-huawei-...`，但另一个
   `...--worktree-remaining-qa` 却改出了**小写开头**的 `c--Users-huawei-...`（其余会话目录
   都是大写 `C--`）。没深挖是哪一步产生的大小写差异。**待查**：`remap_user_projects()` 是否
   有对目录名做过 `.lower()` / 大小写不敏感比较后又用错大小写写回的地方。

6. **import 时 zip 解压/内容改写把所有会话文件 mtime 重置成"迁移那一刻"，`/resume` 排序乱套**。
   `claude_migrate.py cmd_import` 用 `shutil.copyfileobj` 写新文件，mtime 变成写入时刻而非
   原始对话时间；`export` 侧 `zipfile` 默认也不保留/回填 mtime。结果：一次 migrate，几十上
   百个跨月份的旧会话文件 mtime 全变成同一个"迁移时刻"，如果 `/resume` 或会话列表按文件 mtime
   排序，新旧对话的时间顺序就完全乱了。**Codex 同样中招**（`~/.codex/sessions/**/rollout-*.jsonl`
   mtime 也被重置；不过 Codex 按年/月/日文件夹+文件名本身编码了时间，实际影响比 Claude 小）。
   手工修复：jsonl 每行都有 `"timestamp":"..."` 字段，取内容里最大的 timestamp 用
   `os.utime()` 写回文件系统 mtime 即可恢复排序；Codex 侧则是从文件名
   `rollout-YYYY-MM-DDTHH-MM-SS-...` 解析时间戳回填。**修法建议**：`export` 写 zip 时用
   `zinfo.date_time` 记录真实 mtime，`import` 解压后 `os.utime()` 回填，两处都别依赖复制/
   解压的默认行为。

7. **手工修 `installed_plugins.json`/`known_marketplaces.json` 时用 PowerShell `Set-Content
   -Encoding utf8` 写出了带 BOM 的文件，`/plugin` 直接崩**。Windows PowerShell 5.1 的
   `-Encoding utf8`（`Out-File`/`Set-Content` 都一样）会在文件头加 UTF-8 BOM（`EF BB BF`），
   跟 PowerShell Core 的 `utf8` 行为不同，5.1 也没有 `utf8NoBOM` 这个选项。这两个 JSON 文件
   是本项目 bug #2 的手工修复对象，改的时候如果用了 `Set-Content -Encoding utf8`，BOM 就混进
   JSON 开头，Claude Code 的 `/plugin` 走严格 `JSON.parse`，读到 BOM 直接报
   `Unrecognized token '﻿'`，整个 marketplace 配置加载失败。**规避**：改这两个文件（或任何
   会被严格解析器读取的文件）别用 `Set-Content -Encoding utf8`，改用：
   ```powershell
   $utf8NoBom = New-Object System.Text.UTF8Encoding $false
   [System.IO.File]::WriteAllText($path, $content, $utf8NoBom)
   ```
   改完用 `ConvertFrom-Json` 验证一遍。**跟本工具的关系**：`claude_migrate.py`/
   `codex_migrate.py` 自身用 Python 写文件不会加 BOM，不受影响；这条纯粹是给"手工在 Windows
   上patch这几个 json"的人（或 AI agent）的提醒，附带记在这里因为正好是同一批文件。
