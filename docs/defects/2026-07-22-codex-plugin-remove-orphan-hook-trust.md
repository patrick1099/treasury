# 缺陷（平台生命周期缺口）：Codex `plugin remove` 不回收对应 hooks.state

- 状态：**OPEN — 记录在案；不由 hub 直接编辑 Codex config 修复**
- 发现：2026-07-22，Plan 3 T15 §4 cutover 退役旧身份后
- 严重度：Low（惰性孤儿死键，功能无害；但污染「无 xu-local 引用」的整洁性核验）
- 关联：[[2026-07-22-migration-order-dangling-market]]、[[2026-07-22-claude-enable-idempotency-cascade]]

## 现象

cutover 用 `codex plugin remove xu-skills@xu-local` 退役旧身份后，Codex `config.toml` 仍残留一条以旧身份为键的 hook 信任记录：

```toml
[hooks.state."xu-skills@xu-local:hooks/hooks.json:session_start:0:0"]
trusted_hash = "sha256:4105d77de8c79edcbcd1ac353cd5a66972210bb06eea62bc036a53ebf4054af1"
```

`xu-skills` 是 6 个迁移插件里唯一带 hook 的（`hooks/hooks.json` 的 SessionStart→`curation_reminder.py`）。
`plugin remove` 退了插件与其 marketplace 归属，但**没有回收**这条 hook 信任态。

## 判定：惰性孤儿 trust tombstone，不算活动引用

- 它**不含 `plugins-dev` 路径**，只引用一个**已不存在的插件身份** `xu-skills@xu-local`。
- 键 `xu-skills@xu-local:...` 永远匹配不到新身份 `xu-skills@xu-skills:...` → Codex 不会据它做任何信任决策，是死键。
- 官方文档说明 hooks 来自当前活动配置层（https://developers.openai.com/codex/config-advanced#hooks）；
  此记录不对应任何活动插件/市场/来源，判为惰性孤儿。

因此 **retirement 验收标准校准为「无**活动的** plugins-dev 路径 / marketplace / installed plugin 引用」**；
孤立的旧 hook trust tombstone 不计为活动引用（用户 2026-07-22 决定）。

## 为什么不在本机手改修复

- 当前 Codex CLI **没有** `hooks` / `plugin trust` / `plugin revoke` 之类官方清理入口；`plugin remove` 已执行但不回收它。
- hub 的铁律是**平台配置只由官方 CLI 修改，hub 从不直写平台运行态**（cache/installed_plugins.json/known_marketplaces.json/config.toml）。
  手删这条 TOML block 会破坏该铁律。
- 让退役被一个「目前无官方清理入口的无害死键」永久卡住也不对。
- 故：**不删、不改**这条 block，记录在案等 Codex 提供官方回收入口或 hub 侧安全机制。

## 期望的修法（择机，非本次）

- 追踪 Codex 是否提供 hook-trust 的官方回收命令；一旦有，cutover 的退役动作应在 `plugin remove` 后调用它清理该身份的 hooks.state。
- 在此之前，`hub status` 可**只读**报告 `orphan-hook-trust` warning（列出 hooks.state 中不对应任何 manifest 身份的键），
  **绝不自动删除**，仅提示。
- 若未来允许 hub 在**极窄、可审计**的范围内经官方机制回收，再纳入 cutover 收尾。

## 连带：新身份 hook 激活待验证

退役后 `config.toml` **没有**新身份 `xu-skills@xu-skills` 的 hooks.state 条目——说明新身份的 SessionStart hook
尚未被 Codex 信任/记录。**须由用户在下一次 Codex 会话观察原生信任提示确认新 hook 会提示并运行**；
若没有提示或新 hook 不运行，另记「新身份 hook 激活」缺陷，**绝不复用旧 trust**（旧 hash 键不同，也无法复用）。
