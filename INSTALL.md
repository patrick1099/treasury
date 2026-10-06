# 新设备接入 treasury

在新设备打开能执行本地命令的 AI，把下面这段话发给它：

```text
请阅读并执行 https://github.com/patrick1099/treasury/blob/main/INSTALL.md，
把这台设备接入我的 treasury-vault。自动检查环境、拉取仓库、配置本机路径，
接入共享规则和记忆，安装对应的 skills、plugins，并验证是否生效。
沿用金库中参考设备的共享订阅和插件选择。需要本人登录、存在内容冲突，
或无法判断设备用途时再问我；其余步骤连续完成。
```

金库是私有仓库，首次访问需要用户完成 GitHub 登录授权。网页聊天若不能执行本地命令，
只能提供说明；实际安装要交给有本机文件和终端权限的 AI。

下文是给执行安装的 AI 的操作规程。默认接入 Claude Code、Codex 中用户正在使用的平台。
Windows 与 macOS/Linux 的路径、解释器和目录链接由执行者现场识别。
各插件的外部依赖和操作系统限制按它自己的说明核对，基础接入成功不代表所有功能都可用。

## 1. 检查本机，确定落点

先读取已有的 `~/.hub/config.toml`（若存在），复用其中的金库位置、本机设备名和工具仓位置。
新设备默认把两仓分别放在用户目录下的 `treasury`、`treasury-vault`；已被其他内容占用时换空目录。

检查 Git、Python 3.11 以上，以及目标 AI 工具是否可执行。hub 只依赖 Python 标准库。
缺少依赖时按相应工具的官方安装说明补齐；账号登录由用户完成。

把本次用到的值记下来，后文命令都用这些实际值：

| 名称 | 取值 |
|---|---|
| `PYTHON` | 验证可执行的 Python 绝对路径 |
| `HUB_ROOT` | treasury 工具仓的绝对路径 |
| `VAULT_ROOT` | treasury-vault 金库的绝对路径 |
| `HOST_ID` | 新机默认取 Python 的 `socket.gethostname().lower()`；已有绑定沿用原值 |
| 目标平台 | 本机正在使用的 `claude`、`codex`，只启用本次接入的那些 |

Windows 的 Codex 沙箱里，`py` 可能查不到用户安装的 Python，
`python3` 也可能命中商店别名。定位真实的 `python.exe` 后直接用绝对路径调用，
不要照抄旧设备的用户名或 Python 版本目录。macOS/Linux 同样先验证解释器版本。

从即将运行 hub 的同一环境检查插件 CLI：

```text
claude plugin --help
claude plugin marketplace --help
claude plugin list --json
codex plugin --help
codex plugin marketplace --help
codex plugin list --json
```

只运行目标平台对应的三条。当前适配器要求 Claude 有
`install/uninstall/enable/disable/marketplace`，Codex 有 `add/remove/marketplace`。
如果桌面版可用而 PATH 上的同名 CLI 太旧，先修正本次进程的 PATH，再重跑检查。
仅安装桌面 App 不代表终端插件命令已经可用；命令或 JSON 格式不兼容时如实报告，不能跳过插件验收。

## 2. 从 GitHub 拉取两个仓库

| 仓库 | 用途 | 默认分支 |
|---|---|---|
| [patrick1099/treasury](https://github.com/patrick1099/treasury) | hub 命令与这份说明 | `main` |
| [patrick1099/treasury-vault](https://github.com/patrick1099/treasury-vault) | 共享内容、插件源码与设备档案 | `master` |

仓库不存在时 clone 到上一步选定的路径。有 GitHub CLI 时，可先 `gh auth status`，
未登录则让用户完成 `gh auth login`，再使用
`gh repo clone patrick1099/treasury <HUB_ROOT>` 和
`gh repo clone patrick1099/treasury-vault <VAULT_ROOT>`。
已有可用的 Git 凭据或 SSH 时直接 `git clone` 即可。
[GitHub CLI 的 clone 用法](https://cli.github.com/manual/gh_repo_clone)。

私有仓库的匿名网页/raw 链接可能返回 404。此时用已登录的 Git/gh 取文件；
不要把 token 写进文档、远程 URL 或命令输出，也不要创建同名空金库代替它。

目录已是对应仓库时，先看 remote、分支、未提交改动，再更新。
有本机改动时保留并解释冲突；不要用 reset --hard 或清目录的方式重新安装。

进入 `HUB_ROOT`，执行真实解释器对应的：

```text
<PYTHON> -B -m hub.cli --ai-help
<PYTHON> -B -m hub.scaffold_vault --help
```

这里及后文的尖括号是待替换参数，不是可原样粘贴的命令。
带空格的路径须加引号；PowerShell 调用带引号的解释器时前面加 `&`。
hub 的入口是 `-m hub.cli`，不要求系统已存在 `hub` 命令，也不要用 `-m hub`。

## 3. 建立本机设备档案

读取金库根的 `vault.toml`、`SCHEMA.md`、`shared/plugins/manifest.toml`，
以及现有的 `*/device.toml`。金库内旧 SCHEMA 可能落后于工具仓；
字段有冲突时核对 `hub/schema_md.py` 和命令实际行为。

参考设备选择顺序：用户指定的设备 → 金库唯一的已有设备 →
用途、平台相近且最近维护的设备。多份配置用途不同、无法判断时只问一次。

先检查 `HOST_ID` 对应的档案是否属于这台设备。
新电脑与旧电脑同名时，应选一个唯一设备名并一直显式传 `--host`，避免写进旧机备份区。
属于本机的已有档案直接复用、按需补齐，不再次 scaffold。

档案不存在时，依次预演和创建：

```text
<PYTHON> -B -m hub.scaffold_vault <VAULT_ROOT> <HOST_ID> --dry-run --json
<PYTHON> -B -m hub.scaffold_vault <VAULT_ROOT> <HOST_ID> --json
```

scaffold 会生成带占位符的档案，并重生成金库根的 SCHEMA.md。
创建后先完成下面的配置，再运行注册：

- 显式填写顶层 `platforms`。例如只接入 Codex 就是 `["codex"]`；
  省略此字段会启用 hub 认识的全部平台，可能被本机不用的平台依赖阻断。
- 沿用参考设备的 `class`、`projects` 订阅。用户已说明新机用途不同则据此调整；
  这些订阅决定能看到哪些共享记忆，不能只复制文件却留空订阅。
- 重建 `[paths]`：`VAULT` 为本机金库；Claude 配 `CLAUDE_HOME`；
  Codex 配实际 `CODEX_HOME` 和 `AGENTS_HOME`。常规默认分别是
  `~/.claude`、`~/.codex`、`~/.agents`，写入 TOML 时全部展开为绝对路径。
  尊重现有自定义根目录；Codex 的独立 skills 落在 `AGENTS_HOME/skills`。
- 逐个平台复制参考设备的 `[plugins.<平台>].enabled`，
  并与当前 manifest 的存在性、平台适配范围核对。保留原来的停用选择；
  不要把 manifest 中已归档、已替代的插件全部开启。
- 若参考设备配置了 `[skills.<平台>].enabled`，也核对后沿用。
  独立 skill 未配置白名单时默认全部；插件内 skill 在 Claude/Codex 上仍由所属插件整体控制。
- 删除模板中尚不存在的 `[sources.*]` 路径项。新机可以先不配采集源；
  初次接入靠 `shared/` 下行，不需要先 collect。安装后再按实际存在的本机来源补齐。
- 检查已订阅记忆所需的其他符号根，能定位的填本机值。
  无法映射的路径单独列为未就绪项，不把旧机绝对路径当成本机有效路径。

新机没有参考设备时，只启用当前工具，共享记忆先取 global；
插件选择和工作/个人用途合成一次简短确认。不要随意决定一套旧设备的限制。

## 4. 恢复插件各自的 Git 仓库

父金库跟踪的是 `shared/plugins/<名称>/` 的源码文件，插件自己的 `.git` 不随父仓同步。
`register` 可以读取这些源码，后续 `refresh` 和健康检查还需要各插件自己的仓库状态。
当前 CLI 没有 `rehydrate` 子命令，这一步由执行安装的 AI 完成。

对本机启用的插件逐个处理；manifest 若声明了 repository 元数据，也检查该条目的对应仓库：

1. 确认插件目录是金库内的真实目录。用 `git -C <插件目录> rev-parse --show-toplevel`
   检查仓库根是否就是插件目录。返回父金库不算恢复成功。
2. 优先取 manifest 的 `[名称.repository]` 中的 `remote`、`sha`。
   缺 remote 时，可查该插件 `.claude-plugin/plugin.json` 的 `repository`；
   再缺才查参考设备的插件来源记录。不要凭名称猜仓库地址。
3. 先把候选仓库 clone 到独立临时目录。声明了 sha 就校验该提交；
   未声明时以插件版本查 tag、对应版本提交或远端 HEAD，逐个核对源码。
   版本号相同还不够：比较候选提交的跟踪文件集合和内容（忽略 Git 换行转换），
   包括新增、删除的文件；不能只比较 plugin.json。
4. 只有确认候选提交与金库快照一致，才在缺少 `.git` 的插件目录初始化元数据。
   下面命令仅用于本轮新建的嵌套仓，`MATCHED_SHA` 必须是上一步实际匹配的完整提交号：

```text
git init <PLUGIN_DIR>
git -C <PLUGIN_DIR> remote add origin <PLUGIN_REMOTE>
git -C <PLUGIN_DIR> fetch origin
git -C <PLUGIN_DIR> reset --mixed <MATCHED_SHA>
git -C <PLUGIN_DIR> status --porcelain
git -C <PLUGIN_DIR> rev-parse --show-toplevel
```

如果默认 fetch 未取得已匹配的对象，显式获取该提交或包含它的分支/tag。
`reset --mixed` 设置 HEAD 和索引、保留工作目录内容，行为见
[Git 文档](https://git-scm.com/docs/git-reset)。这里不使用会覆盖源码的 hard reset。

最后确认插件仓干净、根目录正确、remote/HEAD 符合匹配结果，
并确认父金库的插件源码没有改动、索引没有 `160000` gitlink。
已存在的嵌套仓先检查，干净且匹配就跳过；有本机修改或不同提交时不要重置。

找不到来源或匹配提交时，保留当前源码并报告具体插件、版本和差异。
不要在原目录新造一个“快照提交”冒充原来的提交，也不要拉最新版覆盖金库快照。
若父仓源码本身不完整，应先在源设备修复并同步，再继续新机安装。

## 5. 接入规则、skills、plugins

先检查目标平台已有的全局规则文件、skills 目录和插件清单，记录原值。
将本次确需修改的已有配置备份到本机金库外的带时间戳目录，保留恢复路径。

共享区的规则与记忆会经 register 接入全局入口。
如果参考设备备份的 `CLAUDE.md` / `AGENTS.md` 还含受管块以外的通用规则，
由 AI 与新机已有规则去重、合并；旧机路径和平台专属命令按本机适配。
有语义冲突时把具体条目交给用户决定。不要整份覆盖全局文件，
也不要把 treasury 仓库自己的开发用 AGENTS.md 当成用户全局规则。

在 `HUB_ROOT` 运行：

```text
<PYTHON> -B -m hub.cli register --vault <VAULT_ROOT> --host <HOST_ID> --dry-run --json
<PYTHON> -B -m hub.cli register --vault <VAULT_ROOT> --host <HOST_ID> --json
<PYTHON> -B -m hub.cli refresh --vault <VAULT_ROOT> --host <HOST_ID> --dry-run --json
<PYTHON> -B -m hub.cli refresh --vault <VAULT_ROOT> --host <HOST_ID> --json
```

每条成功才执行下一条。预演若显示同名内容冲突、意外卸载/禁用或错误的市场换源，
先解释具体变化并处理；常规建链、注册、刷新在本次安装授权内连续完成。
实际插件安装可能部分成功；保留已完成项、修复失败原因后重跑，不能只看最后一条输出。

这两步的分工：

- register 建独立 skill 活链、安装 hub-memory、生成记忆视图和规则受管块，
  并按本机允许列表注册、安装插件。
- refresh 更新视图，并让已安装插件实际重读源码、建立本机刷新基线。
  首次只 register，健康检查可能出现 `no-baseline`。
- Claude 的入口是 `CLAUDE_HOME/CLAUDE.md`。
  Codex 优先使用已有的非空 `CODEX_HOME/AGENTS.override.md`，否则写 `AGENTS.md`。
  受管块以 `hub:begin` / `hub:end` 标识，块外原有内容保留。
- 技能目录本身须是真目录，各个 skill 才是目录链接。插件安装由平台 CLI 完成；
  不要手写平台的缓存、installed_plugins 或 marketplace 状态文件。

需要工具重新加载或用户审阅插件 hook 信任时，明确指出该平台要求的动作。
未完成的登录、信任或重启不能计为已经生效。

## 6. 验收后再结束

在 `HUB_ROOT` 运行，要求退出码为 0、JSON 的 `ok` 为 true：

```text
<PYTHON> -B -m hub.cli status --vault <VAULT_ROOT> --host <HOST_ID> --check --json
<PYTHON> -B -m hub.cli inventory --vault <VAULT_ROOT> --host <HOST_ID> --json
<PYTHON> -B -m hub.cli memory-read --vault <VAULT_ROOT> --host <HOST_ID> --tool <平台> --name <可见记忆名> --json
```

记忆名从本机生成的 `~/.hub/views/<平台>/MEMORY.md` 选取，逐个平台抽查，
确认正文里的路径已正确展开。合法的空订阅应说明没有可读条目，不虚构记忆名。

再检查目标工具的 skill/插件列表，必要时打开一个新会话确认规则和技能能被发现。
`status --check` 通过是 hub 健康证据，不能替代平台实际加载或每个插件外部依赖的验证。

交付给用户四样信息：已接入的平台与插件、两仓及配置的实际位置、
检查结果和仍需本人完成的动作、下次同步的实际命令。失败项写明原因，
不要把“源码下载好了”写成“环境安装完成”。

安装完成后，查看金库 diff，把本轮新增的设备档案与 scaffold 产物逐项核对。
首次接入不必采集旧聊天或推送金库；需要把新设备档案上传时，
在确认 Git 身份和待提交范围后再同步，不把其他会话的改动混进来。

## 以后怎么同步

先读取 `~/.hub/config.toml`，恢复实际的工具仓、金库和设备名。
工具仓干净时可先 `git -C <HUB_ROOT> pull --ff-only` 更新 hub。

只接收其他设备的更新时：

1. 更新前记录金库与启用插件的工作区状态，以及各插件原 HEAD。
   没有本机待提交内容时，对父金库执行 `git -C <VAULT_ROOT> pull --ff-only`；
   分岔或冲突时保留现场处理。
2. 按第 4 节重新核对插件快照与嵌套仓。父金库更新源码后，旧的嵌套 HEAD
   可能尚未更新；确认没有本机修改、源码对应新提交后，再把插件 HEAD/索引对齐该提交。
   不能直接对所有插件 pull 最新分支，替换金库指定版本。
3. 按第 5 节运行 register、refresh，再按第 6 节检查。
   register 负责新加入的 skill/插件，单独 refresh 不会安装尚未安装的插件。

要把本机改动提交并推送到金库时，先看清全部待提交内容，再执行：

```text
<PYTHON> -B -m hub.cli sync --vault <VAULT_ROOT> --host <HOST_ID> --refresh -m "<本次同步原因>"
```

sync 会拉取、校验、提交、推送，并非只下载；它不隐含 collect。
需要备份本机新来源时，先补齐实际存在的 `[sources.*]`，
再单独 `collect --dry-run`、检查计划后 collect，最后同步。
涉及新增或版本变更的插件，仍先完成仓库匹配和 register/refresh 检查。
完整命令与边界见 [hub 使用说明](hub/README.md)。

## 常见卡点

| 现象 | 下一步 |
|---|---|
| 私有仓库 404 / Permission denied | 核实账号权限和 Git/gh 登录，不能改用空金库 |
| scaffold 报本机档案已存在 | 读已有档案并复用，不加 --force 覆盖 |
| register 因不用的平台 unavailable 而失败 | 检查显式 platforms，保留用户选择的目标平台 |
| plugin CLI 缺子命令或 JSON 不兼容 | 定位实际调用的可执行文件，使用兼容版本；不要绕过检查 |
| 同名 skill 被非本来源占用 | 比较内容与来源，冲突由用户决定，先保留原目录 |
| missing-source / dirty / no-baseline | 依次检查插件独立仓库、源码匹配、本机修改和 refresh |
| 缺版本 bump / 源码与提交不符 | 回源插件仓核实版本和同步状态，新机安装不擅自发版 |
| 权限、登录、hook 信任尚未完成 | 说明具体待办并继续可独立完成的步骤，不报全部成功 |

本文提供执行步骤；兼容性以目标设备上的 CLI 和检查结果为准。
