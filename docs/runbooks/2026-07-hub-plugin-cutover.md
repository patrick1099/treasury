# Hub 插件 shared/ cutover runbook

> 这是一次性真机迁移。执行者在每个"人工确认"处停下；不得由 subagent 自动确认。备份目录在最终幂等验收前不得删除。

## 0. 固定路径与身份

```powershell
$HubRepo   = 'C:\Users\huawei\ai-cli-migrate'
$Vault     = 'C:\Users\huawei\hub-vault'
$HostName  = '2025-bg-016'
$OldSource = 'C:\Users\huawei\.claude\plugins-dev'
$Stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'
$Backup    = "C:\Users\huawei\hub-plugin-cutover-$Stamp"
$Input     = Join-Path $Vault 'plugins-migration.toml'

git -C $HubRepo config user.name
git -C $HubRepo config user.email
git -C $Vault config user.name
git -C $Vault config user.email
```

人工确认：两仓都必须是个人身份 `patrick1099`；当前 ai-cli-migrate 预期邮箱为
`245735497+patrick1099@users.noreply.github.com`，hub-vault 当前为 `hsheng416@gmail.com`。若现场不同，先判断原因，
不要由 runbook 静默覆盖现有 Git identity。

## 1. 只读前检与备份

```powershell
git -C $HubRepo status --short
git -C $Vault status --short
Get-ChildItem -LiteralPath $OldSource -Directory | ForEach-Object {
    git -C $_.FullName status --short
}

New-Item -ItemType Directory -Path $Backup | Out-Null
Copy-Item -LiteralPath $OldSource -Destination (Join-Path $Backup 'plugins-dev') -Recurse
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Backup 'claude-plugins.json'),
    ((claude plugin list --json) | Out-String), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $Backup 'claude-markets.json'),
    ((claude plugin marketplace list --json) | Out-String), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $Backup 'codex-plugins.json'),
    ((codex plugin list --json) | Out-String), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $Backup 'codex-markets.json'),
    ((codex plugin marketplace list --json) | Out-String), $Utf8NoBom)
```

停止条件：hub/vault/任一嵌套插件仓有非预期脏改；任一平台 JSON 快照失败；备份目录缺文件。

## 2. 作者检查点：market-of-one 与迁移输入

1. true-north 必须由作者补齐 `.claude-plugin/marketplace.json`，名称、唯一 plugin 名、`source="."`、
   plugin.json name 全等 `true-north`，然后在 true-north 子仓 commit。
2. 作者逐插件填写 `$Input`。`platforms` 是适配声明；`enabled` 是本机允许列表且必须为 `platforms` 子集。
   禁止从平台当前状态自动推断。compact-plus 当前 Claude disabled，不能误写进其 enabled。
3. 对每个插件子仓确认 `git status --short` 为空且 HEAD 已包含最新 manifest/version。

```powershell
py -3 -m hub.cli migrate-schema --vault $Vault --host $HostName --to 3 --dry-run
py -3 -m hub.cli migrate-plugins --vault $Vault --host $HostName --src $OldSource --input $Input --dry-run
```

人工确认：dry-run 必须列出全部 6 仓；`needs_author` 为空；没有未声明/不存在仓；没有真实文件、Git index 或平台状态变化。

## 3. 执行文件迁移（phase 1：只复制，**保留旧源**）

> 三段式的第一阶段。`migrate-plugins` 只复制 + 校验 + induct，**绝不删除旧源**——切指向前保留旧市场根，
> 这样 phase 2 平台 cutover 前 Codex 永远能读到旧市场根，不会整体悬空崩溃（缺陷 dcea199）。旧源退役是 phase 3。

```powershell
py -3 -m hub.cli migrate-schema --vault $Vault --host $HostName --to 3
py -3 -m hub.cli migrate-plugins --vault $Vault --host $HostName --src $OldSource --input $Input
git -C $Vault status --short
git -C $Vault ls-files -s shared/plugins
```

验收：`shared/plugins/<name>/.git` 都存在且子仓 `git log -1` 可读；父仓索引的 shared/plugins 下无 `160000`；
**`$OldSource` 里的旧子仓仍原样保留**（phase 1 不删源）；`shared/plugins/manifest.toml` 与 `plugins-device-snippet.toml` 已生成。
重跑 `migrate-plugins` 是安全幂等的：src+dest 内容/Git 身份一致→只 induct；不一致→冲突拒绝、零删除。
作者审阅 snippet 后，把 `[plugins.claude]`/`[plugins.codex]` 合并进 `<host>/device.toml`，再删 snippet。

```powershell
git -C $Vault add vault.toml SCHEMA.md shared/plugins "$HostName/device.toml"
git -C $Vault commit -m "feat(hub): copy plugin active sources into shared"
```

## 4. 平台 cutover（phase 2，第二个人工闸）

```powershell
py -3 -m hub.cli cutover-plugins --vault $Vault --host $HostName --old-market xu-local --dry-run
```

人工确认：每个旧 `*@xu-local` 都先有新身份 ready 依赖；cjt 同身份换源含重装；最后才删除 xu-local 市场；
没有 manifest 外旧身份。cutover 只走官方 CLI 切平台，**不删任何文件源**。确认后执行：

```powershell
py -3 -m hub.cli cutover-plugins --vault $Vault --host $HostName --old-market xu-local
py -3 -m hub.cli register --vault $Vault --host $HostName
py -3 -m hub.cli status --vault $Vault --host $HostName --check
```

## 5. refresh 与幂等验收

选择一个同时适配 Claude/Codex 的测试插件：在 `shared/plugins/<name>` 修改源码、显式 bump plugin.json version、
在该子仓 commit；然后：

```powershell
py -3 -m hub.cli refresh --vault $Vault --host $HostName
py -3 -m hub.cli refresh --vault $Vault --host $HostName
py -3 -m hub.cli register --vault $Vault --host $HostName
py -3 -m hub.cli status --vault $Vault --host $HostName --check
git -C $Vault status --short
```

验收：第一次 refresh 两平台加载新版本；第二次 no-op；register no-op；status 全 ok；各插件子仓 clean；父仓仅有
预期的子仓内容指针更新。

## 6. 退役旧源（phase 3，第三个人工闸）

> 平台已切到 shared 且 §4/§5 验收通过后，才用显式命令退役旧源。**任一预检失败→零删除**；
> 只删迁移输入声明的旧子仓，**不碰外层容器及其独有文档**（如 `plugins-dev` 自身是个有 GitHub remote
> 的活仓时，先确认它已全推，再单独退役外层——不由本命令代删）。

```powershell
py -3 -m hub.cli retire-plugin-sources --vault $Vault --host $HostName --src $OldSource --input $Input --old-market xu-local --dry-run
```

人工确认：dry-run 列出的待删只有声明的子仓；没有报「退役被拒」。预检覆盖：两平台已无 `xu-local` 市场、
无任何市场/来源指向 `$OldSource`、无 `*@xu-local` 身份、新身份均装且启用策略正确；读不到平台状态也拒绝。
确认后执行；随后备份仍至少保留到下一次正常使用后再删。

```powershell
py -3 -m hub.cli retire-plugin-sources --vault $Vault --host $HostName --src $OldSource --input $Input --old-market xu-local
```

## 7. 回滚

- 文件迁移阶段（phase 1）失败：旧源从未被删（phase 1 只复制），直接停下诊断 shared 现场即可；必要时 `git reset` 父仓。
- 平台 cutover（phase 2）部分失败：不要手改平台文件；修正失败项后重跑 `cutover-plugins`，依赖图会跳过未满足后继。
  **此时不要跑 phase 3**——`retire-plugin-sources` 预检会因旧引用未清而拒绝（零删除），旧源完整保留。
- 新身份不可用：用平台官方 CLI 重新注册备份路径并安装旧身份；不要删除备份或强行改 cache/config。
