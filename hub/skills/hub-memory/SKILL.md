---
name: hub-memory
description: 按名读取 hub 金库共享记忆的正文（在本机该工具视图范围内，自动展开符号根）。当你在自动加载的"共享记忆索引"里看到某条记忆、需要它的完整正文时使用。
---

# hub-memory

自动加载的**索引**（CLAUDE.md/AGENTS.md 受管块或视图文件）只给了 name / 一句话
description / scope；要读某条记忆的**正文**时，用本 skill。

## 怎么用

对当前工具（claude / codex / opencode）跑：

    py -3 <此skill>/scripts/read_memory.py --tool <当前工具> --name <记忆名>

包装脚本会从 `~/.hub/config.toml` 读金库位置与 `hub_root`，转调 `hub memory-read`，
在**本机该工具视图范围内**按名取正文并把符号根（`$VAULT` 等）展开成本机真实路径。
名字不在视图里（不存在或越 scope）会被拒绝——这是有意的，别绕过。

**只读**：本 skill 从不写金库、不改记忆、不落第二份展开文件。
