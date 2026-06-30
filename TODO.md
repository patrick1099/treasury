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
