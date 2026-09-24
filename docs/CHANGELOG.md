# treasury CHANGELOG

> 只记用户感觉得到的变化，专讲为什么。新条目插顶部，旧条目不改写。
> 本文件 2026-09-24 才建立；更早的来龙去脉看 `git log`、`docs/specs/`、`docs/plans/`、`docs/handoff/`。

## 2026-09-24 平台收成注册表；本机停用 opencode / dsh

**起因**：用户 2026-09-23 说"opencode 和 dsh 不管了，我不用了"，当时决定先不动 hub。可 `hub status --check` 一直因"hub 包缺 dsh loader 源码"退出 1，`hub register` 也被同一处拦下、整条跑不了，新 skill 的链接建不出来，只能手建。用户看到这条待办时问："为什么没把可插拔设计好，我们约定的低耦合高内聚呢。"
**根因**：平台这条变化轴一直没收口。平台名单写死在 memwire、status_report、inventory、toggle_ops、memory_ops、scope、cli、plugin_ops 大约十处，调用方到处按平台名分支。结果有两个：想停掉一个平台就得全仓改；一个平台缺了依赖，在 register 里是全局异常，别的平台也跟着停。
**改成**：
- 新增 `hub/platforms/` 注册表，每个平台一个适配器。
- device.toml 顶层 `platforms` 决定本机启用哪些：不写是全部，`[]` 是全停，写错会报错。
- 停用的平台不加载、不探测、不写，也不会被当成"插件不要了"去卸载。
- 启用的平台不可用时，`status` 报 `unavailable`、其余照常检查；`register` / `refresh` 报出全部原因、零写入、返回非零。
- `inventory` 只出启用平台的列，并新增顶层 `harnesses`。
- scope 的 `tool:` 词表和命令行可选值用 hub 认识的全部平台。
- dsh 缺 loader 源码从报"冲突"改为报"不可用"。
- 本机：`platforms = ["claude", "codex"]`；两份旧视图已删；两条 dsh 记忆已归档。

**没选的路**：
- ① 原计划的 device.toml 加 `tools` 白名单、只改三处写死点：治标，下次增减平台还得全仓扫，inventory 和 toggle 仍按名分支。
- ② register 里跳过坏平台、其余照写：codex 评审否掉，因为它违背了"检查全过才写"的既有契约。
- ③ 直接删掉 opencode / dsh 的代码：用户只是暂时不用，留着适配器，改一行就能恢复。
- ④ 这次顺带把 claude / codex 的插件 CLI 方言也搬进适配器：牵扯面大，推后再做。现在按适配器声明的方言分支，遇到未知方言明确报错，不会落进已有方言的默认分支。

**影响**：
- 其他设备的 device.toml 不改，行为不变。
- 本机要恢复 opencode / dsh，把名字加回 `platforms` 即可；dsh 还得先补上 loader 源码。
- 原来按 `plan is None` 判断"没接 opencode"的调用方，改判 `plans == []`。
