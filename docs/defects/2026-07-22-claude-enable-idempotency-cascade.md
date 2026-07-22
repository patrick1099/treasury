# 缺陷（必须修）：Claude 冗余 enable 失败级联跳过退役动作

- 状态：**OPEN — 必须修**
- 发现：2026-07-22，Plan 3 T15 真机 cutover §4 真实执行
- 严重度：High —— cutover 无法在 Claude 侧收尾，留下悬空的旧 `@xu-local` 身份与旧市场，且**不可通过重跑自愈**
- 本机现状：Codex 侧完整切换成功；Claude 侧新身份到位但退役被跳过。未做任何补救、未删 junction、未手改平台配置

## 现象

`cutover-plugins`（非 dry-run）真实执行，末尾 5 个 Claude `enable` 动作失败：

```
✗ keil2clangd:claude:enable      Plugin "keil2clangd@keil2clangd" is already enabled at user scope
✗ true-north:claude:enable       Plugin "true-north@true-north" is already enabled at user scope
✗ xinao-csb-skills:claude:enable Plugin "xinao-csb-skills@xinao-csb-skills" is already enabled at user scope
✗ xu-skills:claude:enable        Plugin "xu-skills@xu-skills" is already enabled at user scope
✗ cjt:claude:cutover-enable      Plugin "cjt@cjt" is already enabled at user scope
```

执行结束态：

- **Codex：完整切换成功。** 5 个 `@<name>` 全 enabled 且 source→`shared/plugins/<name>`；无任何 `@xu-local`；`xu-local` 市场已删；`cjt` 市场 source→shared。
- **Claude：部分完成。** 6 个市场已切到 shared、4 个 `@<name>` 已装且**已 enabled**、`cjt@cjt` 已换源重装并 enabled、`compact-plus@xu-local` 已退役且新 compact-plus 仅注册市场未安装（=禁用）。**但**：4 个旧 `keil2clangd/true-north/xinao-csb-skills/xu-skills @xu-local` 仍在（带悬空路径 error）、`xu-local` 市场仍注册。

## 根因

`claude plugin install <pid> --scope user` **安装即自动在 user scope 启用**。计划紧跟发一条独立
`claude plugin enable <pid>`，此时插件已启用，Claude 返回非零「already enabled」。

`execute_plugin_plan`（`hub/plugin_ops.py:32-45`）把非零返回记为 `failed`；而 Claude 侧
`retire-old`（退役旧 `@xu-local`）与 `retire-market`（删 `xu-local`）动作的 `depends_on`
经 `_ready_dep` 指向该 `enable` 动作。依赖项不在 `succeeded` 里 → 这些退役动作被**级联跳过**
（`plugin_ops.py:33-34`）。

Codex 不受影响：Codex 侧是单条 `codex plugin add`（安装+启用合一，无独立 enable），退役动作依赖的
`add` 成功 → 全部跑完。

## 为什么不能靠重跑自愈

重跑时 `prepare_cutover` 重读平台态：4 个 `@<name>` 已 installed+enabled，install 变 no-op，但独立
`enable` **仍会**返回「already enabled」非零 → 退役**仍被跳过**。必须先修 enable 幂等，重跑才有意义。

## 必须的修法（择一或组合，需 TDD + review）

1. **enable 幂等**：把「already enabled」视为成功（installed+enabled 即达成目标态）。可在
   `run_cli` 之后对 enable 动作做结果归一化，或 enable 前先查状态、已启用则跳过并记 succeeded。
2. **install 后不再无条件补发独立 enable**：若平台 install 默认即启用，则仅在「实测未启用」时才 enable。
   注意 Claude 与 Codex 的默认启用语义不同，需分平台建模。
3. **退役动作的 depends_on 不应挂在冗余 enable 上**：`retire-old`/`retire-market` 的「新身份就绪」
   依赖应指向真正代表就绪的动作（install 成功且已启用），而非可能冗余失败的 enable。

推荐 1+3：让「already enabled」成为幂等成功，并复核 `_ready_dep` 的就绪判定，使退役只依赖真实就绪信号。

## 回归测试（必须补）

- **Claude install-auto-enable 幂等**：模拟 `install` 后插件已启用、独立 `enable` 返回「already enabled」，
  断言该动作被视为成功、且下游 `retire-old`/`retire-market` 不被跳过。
- **跨平台一致**：同一 manifest 下 Claude（install+enable 两段）与 Codex（add 一段）都应完整走到退役与删市场。
- 幂等重跑：cutover 在「已部分/全部达成目标态」上重跑应收敛为 no-op，不因「already enabled/installed」误判失败。

## 与 dangling-market 缺陷的关系

见 `2026-07-22-migration-order-dangling-market.md`。两者独立：前者是迁移顺序（§3 删旧源过早），
本缺陷是 cutover 执行器对 Claude 冗余 enable 的非幂等处理。修复时应一并纳入三段式迁移协议的 cutover 阶段。

## 本机遗留态（待用户决策，未补救）

- 未手改平台配置、未删 cjt junction、未重跑 cutover。
- Claude 侧遗留：`keil2clangd/true-north/xinao-csb-skills/xu-skills @xu-local` 4 个悬空身份 +
  `xu-local` 市场未删。功能上目标 `@<name>` 均已启用可用，遗留仅为旧副本。
