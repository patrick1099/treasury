# 缺陷（必须修）：迁移顺序在平台改指向前删除仍被引用的市场根

- 状态：**FIXED（2026-07-22，三段式迁移已实现，TDD + 独立 review + 全量回归）**
- 发现：2026-07-22，Plan 3（`docs/plans/2026-07-20-hub-c-plugin-register.md`）T15 真机 cutover §4 起手
- 严重度：High —— 会让 Codex 插件子系统在 §3 与 §4 之间整体瘫痪（不止被迁插件，所有已装 Codex 插件一起不可用）
- 本机现状：已用**临时 junction 兼容桥**恢复并完成 cutover，桥已安全移除（历史记录见文末）

## 修复摘要（2026-07-22）

三段式迁移落地，切指向前绝不删旧市场根：
1. **`migrate-plugins`(phase1)**：`_do_move`→`_do_copy`——只 copy+校验+induct，**绝不删源**。
   重跑允许 src+dest 共存：`_same_repo`(HEAD+remote+去 .git 内容清单)一致→幂等只 induct；不同→冲突拒绝、零删除。
2. **`cutover-plugins`(phase2)**：只官方 CLI 平台切换，不删文件源（行为不变）。
3. **`retire-plugin-sources`(phase3，新命令)**：`prepare_retire`/`execute_retire`——全量预检两平台已无旧
   marketplace/source/身份引用（读不到平台状态也拒绝）+ 新身份均装且启用策略正确；任一失败→零删除；
   只删迁移输入声明的 `src_dir/<name>`，不碰外层容器及独有 docs；`--dry-run` 与真跑共用 planner/executor，删除前保留人工闸。

回归测试见 `tests/hub/test_plugin_retire.py`（含 Codex 悬空市场→读不到→零删除、Claude 容忍/Codex 不容忍差异 fixture）
与 `test_plugin_migrate_exec.py`（phase1 保源、重跑幂等、内容漂移拒绝、Codex 旧市场根 cutover 前始终可读）。
runbook §3/§6/§7（phase3 退役在 §6，回滚顺延 §7）、spec P8、hub/README CLI 帮助已同步。**下方原始分析保留作历史。**

## 现象

`migrate-plugins`（§3）把 6 个插件仓从 `~/.claude/plugins-dev/<name>` 搬进 `hub-vault/shared/plugins/<name>` 后，平台侧的市场根指向悬空：

- `cjt` 市场根 = `plugins-dev\cjt`，**整个目录已消失**
- `xu-local` 市场根 = `plugins-dev`（目录还在，但 5 个子插件源已搬走）

Claude 对悬空市场**能容忍**（`plugin list --json` 照列，附 `errors` 字段）。
Codex **不能**：它在任何插件操作前**预加载全部已配置 marketplace 快照**，`cjt` 根消失即整体报错——

```
codex plugin list --json
Error: failed to load configured marketplace snapshot(s):
- `cjt` at \\?\C:\Users\huawei\.claude\plugins-dev\cjt: marketplace root does not contain a supported manifest
```

`cutover-plugins`（§4）第一步就是 `installed_plugins("codex")` + `marketplaces("codex")`
（`hub/plugin_migrate.py:230`），CLI 返回非零 → `hub/plugin_cli.py:_json` 抛 `CliUnavailable`
→ dry-run 连计划都算不出来。

## 根因

**迁移顺序错了**：§3 先删除（移走）消费者仍在引用的源，§4 才准备把消费者切换到新源。
在「平台市场根仍指向旧路径」的窗口里，旧根已经不存在了。对 Codex 这类「预加载全部快照、任一坏即整体崩」的消费者，这个窗口是致命的。

现有 `cutover-plugins` 假设「§3 搬完后平台仍可被枚举」——该假设对 Claude 成立，对 Codex 不成立。

## 必须的修法：三段式迁移，先切指向后退役旧源

把迁移拆成三个**不可合并**的阶段，旧源在平台切换成功前一直保留：

1. **复制 + induct，但保留旧源**：把仓库内容装入 `shared/plugins/<name>` 并让父仓跟踪其文件
   （induction，零 gitlink），**不删除** `plugins-dev/<name>`。此阶段结束后两处都是可加载的活源。
2. **平台 cutover**：通过官方 CLI 把每个市场根从旧路径切到 `shared/plugins/<name>`，安装/启用新身份，
   退役旧身份，最后删旧聚合市场。全程平台始终能加载到某个有效根（切换前是旧根，切换后是新根）。
3. **成功后退役旧源**：平台全部指向 `shared/` 并验证通过后，才删除 `plugins-dev/<name>`。

关键不变量：**在平台把市场根改指向新路径之前，绝不删除仍被任何平台引用的旧市场根。**

## 明确的非目标（不要这样"修"）

- ❌ **不要**用「枚举失败时从 config.toml 猜安装/启用状态」当正式修复。那只让 planner 绕过查询；
  真实执行时 Codex CLI 仍会因悬空市场继续崩，且无法可靠获知真实安装/启用态。这是治症状不是治根因。
- ❌ **不要**靠每台新机器手工改 Codex config 或手工删悬空市场来兜底。

## 回归测试（必须补）

- **Codex 悬空市场回归**：构造「一个本地市场根在 `plugin list`/`marketplace list` 前被移走」的场景，
  断言迁移协议不会进入这种平台被整体拖垮的中间态（即验证三段式顺序：旧源在平台切换成功前始终存在）。
- 覆盖「Claude 容忍悬空、Codex 不容忍」的差异，防止只按 Claude 行为假设写实现。

## Runbook / 迁移协议须改

- `docs/runbooks/2026-07-hub-plugin-cutover.md`：把 §3「执行文件迁移」改成「复制+induct 保留旧源」，
  §4 平台 cutover 之后新增一节「成功验证后退役旧源」。§3 不再删除 `plugins-dev` 的 6 个旧仓。
- 迁移协议文档同步：明确三阶段与「切指向前不删旧根」不变量。

## 本机临时兼容桥（退役条件）

因本机已处于「§3 已删旧源、§4 未切」的错误中间态，用临时 junction 恢复 Codex 而不手改 config：

```powershell
New-Item -ItemType Junction `
  -Path 'C:\Users\huawei\.claude\plugins-dev\cjt' `
  -Target 'C:\Users\huawei\hub-vault\shared\plugins\cjt'
```

junction 透视到唯一的 shared 活源（HEAD 一致，无第二份拷贝）。仅 `cjt` 需要桥（只有它的**市场根**整个消失；
`xu-local` 根 `plugins-dev` 仍在故不致崩）。

**退役条件**：真实 cutover 通过官方 CLI 把 `cjt` 市场切到 `shared/plugins/cjt` 并验证成功后，
再 `Remove-Item 'C:\Users\huawei\.claude\plugins-dev\cjt'` 移除该 junction。在此之前不删。
