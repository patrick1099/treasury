# 交接：`ai-cli-migrate` → `treasury` 改名（2026-08-12）

> **状态：已于 2026-08-12 执行完毕。** 执行记录、与本方案的偏差、遗留项见文末 §十一。
> 冷启动读这一份就够，不用回翻对话。
> 相关背景在 `docs/NEEDS.md`（项目定盘星）和 `docs/specs/2026-07-09-shared-data-layer-mvp-design.md` §9（"hub 是产品"那段）。

## 一句话

两个仓改名：**`ai-cli-migrate` → `treasury`**，**`hub-vault` → `treasury-vault`**。
只改**仓库名 + 本地目录名 + 配置里的绝对路径**三层；
Python 包 `hub/`、命令形态 `hub <子命令>`、运行时目录 `~/.hub` **一律不动**。

---

## 一、为什么要改（不是审美问题）

四条证据，任一条单独都够：

1. **量摆着**（2026-08-12 实测，`__pycache__` 已排除）：

   | 区域 | py 文件 | py 行数 |
   |---|---:|---:|
   | `hub/`（数据层） | 49 | 5477 |
   | 顶层迁移四件套（`migrate.py` / `claude_migrate.py` / `codex_migrate.py` / `pack_migration.py`） | 4 | 1447 |
   | `tests/` | 71 | 7017 |

   `hub/` 占生产代码约八成。名字里的 migrate 指的是那个小的、旧的那半。

2. **迁移工具根本不在 hub 里**。hub CLI 有 15 个子命令（status / sync / collect / bootstrap /
   register / refresh / promote / promote-memory / induct / migrate-schema / migrate-plugins /
   cutover-plugins / retire-plugin-sources / memory-read / secrets），换机迁移是**另一个独立入口**
   `migrate.py`。注意 `migrate-schema` / `migrate-plugins` 是**金库 schema 的版本迁移**，
   跟"换电脑"无关，别被名字骗了。

3. **项目内部早就自称 hub**：`docs/NEEDS.md` 的标题是「hub NEEDS —— 定盘星」，
   `~/.hub/config.toml` 里那个字段叫 `hub_root`。只有仓库名还停在 2026-07 之前。

4. **这是计划内的过期，不是长歪**。2026-07-09 的 spec §9 白纸黑字写着：

   > **hub 是产品**；`ai-cli-migrate` 的内脏（存储位置知识、SQLite 安全快照、path/user remap、
   > plugin-json 手术）**降级为 hub 的底层工具箱**。

   "migrate 让位、hub 上位"那天就定了，只是没人去执行改名这一步。

### 迁移工具不要拆出去

`NEEDS.md` 里"换机能照金库还原"是需求①的第四条，而 hub 的 **C 阶段（加载器）还没开始**——
`migrate.py` 目前是唯一能真换机的东西，`TODO.md` 里还挂着 7 个真机实测出的未修 bug。
它是 hub 的一个阶段性组成，不是遗留物。

---

## 二、为什么不继续叫 hub

`hub` 这个词的出处查清了，不是随手起的：

- 出自 2026-07-09 spec 的标题「**跨工具/设备 共享数据层（hub）**」，即 **hub ≡ 共享数据层**，
  比 `hub/` 这个 Python 包早两天（包骨架 `9d17749`）。
- 取的是 **hub-and-spoke 轮毂**义——§9 管每台设备叫 **spoke**
  （"`hub bootstrap` ＝ 首次在一台新 **spoke** 落地"）。中心只有一个，改中心则所有辐条同时变。
- **但同一份 spec 又把拓扑定成对等的**：「离线优先、对等树、每台设备都是完整处理节点，
  NAS 只是一个方便的公共 remote」。所以 hub 指的是**逻辑上的唯一活源**，不是一台要连上去的服务器。

名字同时想说"中心"和"不是中心"，这是它读起来空的根源。加上用户判断：**hub 在开源世界太泛滥，等于没起名。**

---

## 三、名字是怎么定下来的（避免下一轮重走弯路）

用户给的语义锚，原话：

> 核心理念是共享，一份源，分发。里面存着我的数据，确实也有金库的含义。

即四层要求：**共享**（多工具多机器吃同一份）→ **一份源**（唯一活源）→ **分发**（改一处处处生效）
→ **库**（装的是自己的东西，贵重、要守）。

**淘汰过的三个方向，别再往回走**：

| 方向 | 试过的名字 | 淘汰原因 |
|---|---|---|
| 单词文学 / 职衔系 | `curator`、`quartermaster`、`steward` | 跟用户命名空间不是一路——他的仓名一水儿直白（`code-jump-tags`、`note-workflow`、`repo-keeper`、`keil2clangd`），最"文艺"也就 `true-north` / `ai-room` 这种两词轻隐喻。另外 `steward` 跟 `repo-keeper` 在中文里都是"管家"，撞词 |
| 容器系 | `kitbag`、`carryall`、`ai-holdings`、`homebase` | 只碰到"库"，把"源"和"分发"整个丢了。容器是死的，源是活的、会往外流 |
| 水系 | `wellspring`、`wellhead`、`fount`、`reservoir` | 语义上最贴"一份源 + 分发"，但装的是数据不是水，"我的 / 贵重"这层缺失 |

**最终选 `treasury`**：国库这个词妙在**既存也发**（存金、发行），"库"和"分发"在同一个词里。

**已知瑕疵，用户知情后仍然选它**：`treasury-vault` 有"库-库"重复。
下一个人不要拿这一点回头重开命名讨论——**这是用户拍过板的。**

---

## 四、改哪一层，不改哪一层

| 层 | 现在 | 这次 | 代价 |
|---|---|---|---|
| GitHub 仓库名 | `ai-cli-migrate` / `hub-vault` | ✅ 改 | 几乎免费，旧名自动 302 重定向，clone URL 继续能用 |
| 本地目录 | `~/ai-cli-migrate` / `~/hub-vault` | ✅ 改 | 见 §五清单，机械替换 |
| 配置里的绝对路径 | 4 个文件 | ✅ 改 | 见 §五清单 |
| **Python 包名** | `hub/`（`from hub import cli`） | ❌ 不改 | 要动 49 个源文件 + 71 个测试文件的 import |
| 命令形态 | `hub <子命令>`（**不在 PATH 上**，见下） | ❌ 不改 | 跟包名绑一起 |
| 运行时目录 | `~/.hub/`（config / views / plugin-state / secrets-profiles / backups） | ❌ 不改 | 写死在 10 个 py 文件里（`cli.py`、`hubconfig.py`、`memview.py`、`memwire.py`、`plugin_state.py`、`schema_md.py`、`secrets_profile.py`、`status_report.py`、`writer.py`、`skills/hub-memory/scripts/read_memory.py`） |

**分层理由**：包名是内部实现名，GitHub 上看不见；对外叫 treasury、内部实现叫 hub 是正当分层。
深层日后想改随时能改，**71 个测试文件就是那道闸**，不必跟改名这件事捆绑。

> ⚠️ `hub` **不在 PATH 上**，也没有 `__main__.py`。正确调法是从仓库根
> `py -3 -c "from hub import cli; raise SystemExit(cli.main([...]))"`，`--vault` 必填。

---

## 五、完整改动清单（数字为 2026-08-12 实测）

### 配置文件（4 个，必须与目录改名同一步完成）

| 文件 | 改什么 | 处数 |
|---|---|---:|
| `~/.claude/settings.json` | PreToolUse hook 命令里的 `ai-cli-migrate` | 1 |
| 同上 | `extraKnownMarketplaces` 里 9 条市场的 `source.path` 中的 `hub-vault` | 9 |
| `~/.claude/plugins/known_marketplaces.json` | 9 条 directory 市场的 `source.path` + `installLocation` | 18 |
| `~/.hub/config.toml` | `vault`（hub-vault）+ `hub_root`（ai-cli-migrate） | 2 |
| `~/hub-vault/2025-bg-016/device.toml` | `[paths] VAULT` | 1 |

> `known_marketplaces.json` 共 10 个市场，其中 `claude-plugins-official` 是 github 源、
> installLocation 在 `~/.claude` 下，**不用动**。

### 两个仓内的文字

| 仓 | 提 `ai-cli-migrate` 的文件 | 提 `hub-vault` 的文件 |
|---|---:|---:|
| `ai-cli-migrate` | 15 | 10 |
| `hub-vault` | 9 | 15 |

金库那 15+9 处多数是**记忆正文里的叙述**；`<host>/claude/CLAUDE.md`、`<host>/codex/AGENTS.md`、
根 `MEMORY.md` 是**生成物**，跑一次 `collect` / `refresh` 会自己重算，不用手改。

### 其他

- 两仓的 `git remote set-url`
- 桌面快捷方式「一键打包迁移包」指向旧路径的 `打包.bat`
- 本项目记忆 2 条：`~/.claude/projects/C--Users-huawei-Desktop-MyProjects-Commercial-Ultrasonic-Modular/memory/`
  下的 `hub-cli-not-on-path.md` 和 `MEMORY.md`

---

## 六、执行顺序 —— 有一步会把自己锁死

### 坑：配置是会话启动时读进内存的

`~/.claude/settings.json` 里那个 PreToolUse hook 写死
`C:/Users/huawei/ai-cli-migrate/hub/hooks/secrets_guard.py`，**match 的是
`Read|Edit|Write|Grep|Glob|Bash|NotebookEdit`——几乎所有工具调用**。
插件市场那 9 条路径同理。改了文件不会当场生效，**目录一改名，本会话剩下的每次工具调用
都会去执行一个不存在的脚本**。

### 解法：旧路径留 junction

`cmd /c mklink /J <旧路径> <新路径>`，**不需要管理员权限**。新旧两条路都通，
等下次重启 Claude Code 验证无误再删掉 junction。这招在 2026-07-22 金库插件迁移时用过
（当时是 `plugins-dev\cjt` → `shared\plugins\cjt`）。

### 步骤

1. **单个 python 脚本一口气做完，中间不留窗口**：
   目录改名（两个）→ 改 4 个配置文件 → 旧路径建 junction（两个）。
   分成多次工具调用会在中间暴露出锁死窗口。
2. 验证（见 §七）。
3. 两仓 `git remote set-url` → GitHub 改名（`gh repo rename`）。
4. 改两仓内的 README / docs 自称；金库记忆正文里的路径叙述；本项目那 2 条记忆。
5. 各自 commit + push。
6. 跑一次 `hub collect` + `hub sync --refresh`，让生成物（`CLAUDE.md` / `AGENTS.md` /
   `MEMORY.md` / `<host>/<tool>/plugins.toml`）重算。
7. **重启 Claude Code 验证通过后**，删掉两个 junction。

> **写入方式**：Esafenet 透明加密按扩展名全机生效。改 `.py` / `.toml` 必须走 python
> 或 Claude Code 自己的 Write/Edit，**禁止 PowerShell 的 `Set-Content` / `Copy-Item`**——
> 那会把文件脱密落盘且退出码全绿、`git diff` 干净，零痕迹。

---

## 七、验证清单

- [ ] `~/.claude/settings.json` 和 `~/.claude/plugins/known_marketplaces.json` 都是合法 JSON
- [ ] 全机 grep `ai-cli-migrate` / `hub-vault`，只剩历史叙述，没有活指针
- [ ] `hub status --vault C:/Users/huawei/treasury-vault` 跑通
- [ ] 9 个插件市场的 path 都指向存在的目录
- [ ] `pytest` 全绿（改名不该动到测试，绿不了说明有路径写死在代码里）
- [ ] `gh repo view patrick1099/treasury` / `treasury-vault` 都在
- [ ] **重启 Claude Code**，确认 skill / 插件正常加载、hook 不报错
- [ ] 桌面快捷方式能双击跑通

## 八、回滚

三层各自独立可回：GitHub 用 `gh repo rename` 改回去；目录 `mv` 回去；
配置文件从 git（金库侧）或直接反向替换。**junction 在，回滚窗口就一直开着**，
所以第 7 步"删 junction"必须排在验证之后。

---

## 九、未决项

1. **深层改名要不要做**（Python 包 `hub/` → `treasury/`、`~/.hub` → `~/.treasury`、
   命令形态）。本次明确不做。做的话是一次纯重构，71 个测试文件是闸。
2. **`treasury-vault` 的"库-库"重复**。已向用户提出，用户仍选此名。**不要重开。**
3. 改名之后 `docs/` 里那批老 spec / plan 的标题仍写 `ai-cli-migrate`。
   建议**不追改历史文档**（它们是当时的记录），只改 README、NEEDS.md 这类"当前状态"文档。

---

## 十、同一会话里已经做完的相邻改动（背景，免得误判）

下一个人如果发现 `shared/plugins/` 少了个目录，别以为出事了：

- **9 个 GitHub 仓已归档**：`keil2clangd`、`claude-plugins-dev`、`compact-plus`、`Mars`、`ULS`、
  `pressure_gauge`、`MuSAS`、`MuSAS-GUI`（加上原本就归档的 `true-north`）。前三个的
  description 里写了归档说明和继任者。
- **compact-plus 已完整下架**：GitHub 仓归档、`$VAULT/shared/plugins/compact-plus/` 源已删、
  `manifest.toml` 与 `known_marketplaces.json` 与 `settings.json` 的
  `extraKnownMarketplaces` 三处条目已清。要旧代码从归档仓 clone。
  记忆 `reference_lossless_compaction_hooks` 已改写成墓碑（只留"省钱优先于不丢"的取舍
  和一串写 hook 会撞的坑）。
- 金库对应提交：`9db6042`（下架）、`a87c783`（collect 刷新快照）。

---

## 十一、执行记录（2026-08-12，本方案已落地）

### 本方案漏掉的三类活指针 —— 下次改目录名必看

飞行前扫描逼出三类 §五 完全没列的东西，**共同点是文本 grep 结构上看不见或没想到扫**：

| 漏掉的 | 数量 | 漏了会怎样 |
|---|---:|---|
| **Windows junction** | **54** | `.claude/skills` 5、`.config/opencode/skill` 44、`.agents/skills` 5。目标路径存在 reparse point 里，不在任何文件内容中。旧路径留兼容 junction 时靠**链式解析**还活着，**删兼容 junction 那一刻全断** |
| **`~/.gitconfig` 的 `includeIf "gitdir/i:C:/Users/huawei/hub-vault/"`** | 1 | 金库里新建的无 remote 子仓，首个 commit **静默落成公司身份 `xrh`**。金库记忆 `reference_git_identity_separation` 里白纸黑字记着这条规则 2026-07-23 已经因目录改名死过一次 |
| `~/.claude.json`（2 处）、`~/.codex/config.toml`（9 处） | 11 | 列 §五 清单时纯粹没想到扫这两个文件 |

正确的扫法是两条腿：文本 grep 要带上 `~/.gitconfig` `~/.claude.json` `~/.codex/`；
另外必须单独跑 `Get-ChildItem <各根> -Recurse -Force | Where-Object { $_.LinkType }` 扫链接。

### 实际怎么做的

一个 python 脚本（`--apply` 闸，dry-run 与真跑共用同一条写路径）一口气完成：
两个目录改名 → 旧路径建兼容 junction → **重指 49 个 junction** → 重写 6 个配置文件。
`.agents/skills` 那 5 个是 `hub status` 的输出暴露出来的，事后用同一个脚本补修。

改后实测各处处数与 §五 一致：settings.json 10（1 hook + 9 市场）、known_marketplaces.json 18、
`.codex/config.toml` 9、`.hub/config.toml` 2、`.claude.json` 2、device.toml 1。

### 验证结果

- `pytest` **621 passed / 3 skipped** —— 印证 §四 的判断：代码里**没有一处功能性硬编码路径**，
  `hub/guard.py`、`migrate.py`、`schema_md.py`、两个测试里的命中全是注释/示例串/测试假路径。
- 全机 junction 复扫：**0 悬空、0 指向旧名**。
- 三个 JSON 改后仍合法；`hub status --vault .../treasury-vault` 跑通。
- gitconfig 规则实测：金库内新建无 remote 仓 → `patrick1099`（个人身份），已复原。
- GitHub `patrick1099/treasury` 与 `treasury-vault` 均在，旧名 302 重定向。

### 有意没做的

- **`hub/README.md` 里的 `D:/hub-vault` 示例路径**：那是通用脚手架示例（`<你>` 占位那类），
  不是本机路径。
- **`xu-skills` 插件里 `curating-memory/references/hub-regime.md` 与 `EVAL.md`**
  的示例路径仍写旧名：改插件文件要触发 bump version + 推子仓 + `hub sync --refresh` 整套发布仪式，
  为一处示例串不值。**留作下次动 xu-skills 时顺手改。**
- `docs/` 下的老 spec / plan / defect / runbook 与 `.superpowers/` 台账：按 §九.3 不追改历史文档。
- 记忆 `reference_claude_migrate_tool` 的**文件名没改**（内容已更新）。改名要连带
  改反向链接和索引，属金库整理动作，等下次 `curating-memory` 一并处理。

### 兼容 junction 还在

`~/ai-cli-migrate` → `~/treasury`、`~/hub-vault` → `~/treasury-vault` 两个兼容 junction
**尚未删除**，回滚窗口一直开着。按 §六 步骤 7，**重启 Claude Code 验证插件/skill/hook 全部
正常加载之后**才能删。删法：`cmd /c rmdir "C:\Users\huawei\ai-cli-migrate"`（**绝不带 `/S`**，
带了会连目标内容一起删）。
