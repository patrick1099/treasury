# hub —— 把本机 AI 工具的家当收进一个 git 金库,再活链回各工具

`hub` 目前有两个**边界明确**的阶段,都在这个仓库里:

- **A 提取器(`collect` / `sync`)**:读本机 Claude Code / Codex 的配置与产出,**只**收进金库的
  **备份区**。**绝不把内容写回工具地盘,也不写 `shared/`。**
- **C 注册器(`promote` / `promote-memory` / `register` / `refresh` / `migrate-schema` / `status`)**:
  由用户**显式调用**。`promote` 把选定 skill 从备份区**复制**进 `shared/`;`register` 把 `shared/` 的 skill
  **逐个 junction** 链进 Claude / Codex / opencode 的 skill 目录(改一处三家实时生效);memory 走
  `promote-memory` 上行 + `register`/`refresh` 下行生成只读视图(见 §7)。plugin 见后续计划。

> **事故铁律(主语已收窄)**:它约束的是**自动提取流程**——`collect` / `sync` 永远不能顺手把备份
> 落回真实工具目录。上一版有个会往 `~/.claude` 乱写的"落地层",已**整个删掉**;若在别处看到
> `hub.cli process` / `hub.cli pull` / `materialize.py` / `roster.py` / `managed_block.py`,那是过时文档。
> **C 阶段的写入不走自动流程**:只经用户显式调用的 `promote` / `register`,且都过独立安全闸——
> 冲突即停、不覆盖用户内容、link-only、支持 `--dry-run`。

纯标准库,Python ≥ 3.11(实测 3.14)。

---

## 1. 两个角色

| 谁 | 是什么 | 写哪儿 |
|---|---|---|
| **A 提取器** | Python,机械搬运,不做判断 | **只写 `<本机>/`** 备份区,外加金库根的派生索引 `MEMORY.md` |
| **C 注册器** | 判断题;skill-loop(`register`/`promote`/`status`)与 memory 视图下行(`promote-memory`/`register`/`refresh`/`migrate-schema`,见 §7)已在本包,plugin 见后续计划 | `shared/`、各工具 skill 目录、`~/.hub/views/`、各工具受管块/opencode 配置(经用户显式调用 + 安全闸) |

两阶段之间的接口是金库根的 **`SCHEMA.md`**(由 `hub/schema_md.py` 生成)——它定义金库长什么样。
后续独立的加载器(memory / plugin)仍以这份契约为准。

**要了解金库的格式、字段语义、硬闸行为、重写粒度——去读 `SCHEMA.md`,不要读这份 README。**
这份 README 只讲"怎么跑这个 Python 包";`SCHEMA.md` 讲"金库是什么"。不重复,免得两边打架。

---

## 2. 两个区

    <金库>/
    ├─ vault.toml  SCHEMA.md  MEMORY.md  lint-exempt.txt
    ├─ <本机名>/         备份区:这台机的原始数据,按工具分
    │   ├─ device.toml
    │   ├─ claude/  memory/ skills/ plugins/ hooks/ chats/ plugins.toml CLAUDE.md
    │   └─ codex/   skills/ hooks/ chats/ plugins.toml AGENTS.md
    └─ shared/           共享区:跨设备/跨工具的精选,按类型分

- **备份区 = "别丢"**(换机照它还原)。提取器只写这里。
- **共享区 = "到处都要有"**(加载器照它装)。**提取器从不写这里。**

`<本机名>` = `socket.gethostname().lower()`。每台设备只写自己那个文件夹 → 两台机永远
碰不到同一个文件 → git 合并天然零冲突。

---

## 3. 快速开始

```bash
# 1) 建金库骨架 + 本机设备档案模板(金库本来就是个 git 仓,先 git init 完全正常)
git init D:/hub-vault
py -3 -m hub.scaffold_vault  D:/hub-vault  mybox

# 2) 编辑 D:/hub-vault/mybox/device.toml,把所有 <...> 占位符换成本机真实路径
#    ★ 配了的源必须真的存在;用不到的项就整行删掉(缺项 = 本机没那个源,是合法的)

# 3) 收集本机的记忆/skill/插件进金库(先看看会发生什么)
py -3 -m hub.cli collect  --vault D:/hub-vault --dry-run
py -3 -m hub.cli collect  --vault D:/hub-vault

# 4) 校验 + 重生成索引 + 提交 + 推送(金库加了 git remote 才需要)
py -3 -m hub.cli sync     --vault D:/hub-vault
```

> **第 2 步不是可选的。** `device.toml` 刚生成时里面全是 `<占位>`,那些路径不存在。
> 提取器会**拒绝执行**并点名是哪个路径 —— 这是有意的:配错的源路径**不等于**
> "用户把记忆全删了",绝不能顺着镜像语义把金库清空(见 `SCHEMA.md` §3)。

---

## 4. 命令一览

所有命令都吃 `--vault <金库>`,可选 `--host <设备名>`(省略 = 本机 hostname 小写)。

| 命令 | 作用 | 联网 |
|---|---|---|
| `collect` | 读本机的源,填 `<本机>/` 备份区,重算 `MEMORY.md` | 否 |
| `sync` | 拉取合并 → lint(scope / 裸路径 / sensitive)→ 重算索引 → 提交推送 | 是 |
| `promote` | 把备份区选定 skill **复制**进 `shared/`(同名不同内容即停);`--tool <claude\|codex> --name <skill 名>` | 否 |
| `promote-memory` | 把备份区选定记忆**复制**进 `shared/memory/`(同名不同内容即停);`--name <记忆名>` 或 `--all`(批量、非 mirror) | 否 |
| `register` | 把 `shared/skills/` 逐个**活链**进各工具(Claude `~/.claude/skills`、Codex/opencode `~/.agents/skills`);装 `hub-memory` skill;首建 memory 视图 + 受管块 + opencode 条目;改一处三家实时生效;非破坏,冲突即停不写 | 否 |
| `refresh` | `shared/` 变化后重算 memory 视图 + 受管块 + opencode 条目(skill 是活链不用刷) | 否 |
| `migrate-schema` | 金库 `vault.toml` 的 scope 语法版本迁移;`--to 2`,只从 version 1 升、且要求全部记忆已是 `[global]`,否则列清单拒绝 | 否 |
| `status` | 金库的 `git status --porcelain`,再附各工具的 skill 链接健康(`ok` / `missing` / `conflict`);`--check` 另做 C 阶段健康检查(hub-memory 链、`~/.hub/config.toml`、三份视图、受管块、opencode 条目、新鲜度),不健康返回非零 | 否 |
| `bootstrap` | (兼容 / 旧入口)换新机时把金库里的加载器 skill 装进各工具,然后退场 | 否 |
| `hub-scaffold`(`python -m hub.scaffold_vault`) | 建金库 / 把一台新设备加进已有金库 | 否 |

- `collect` / `promote` / `promote-memory` / `register` / `refresh` / `migrate-schema` / `bootstrap` 都支持
  **`--dry-run`**(一个字节都不落盘,只打印会写什么);`collect` / `bootstrap` 另有 **`--yes`**(不询问,直接执行,含删除)。
- `scaffold` 的参数是**两个位置参数** + `--force` / `--dry-run`:
  `py -3 -m hub.scaffold_vault <金库目录> <设备名>`。
- `memory-read`(`--vault --host --tool <claude\|codex\|opencode> --name <记忆名>`)是 memory 正文的读取入口,
  **正常不手敲**——由随包的 `hub-memory` skill 调用(装在 `~/.claude/skills/hub-memory` /
  `~/.agents/skills/hub-memory`,`register` 建链);只解析本机该 `--tool` 视图里的名字,拒读越 scope 记忆。

**会写备份区以外位置的命令(都非自动、都过安全闸)**:`register`(在各工具 skill 目录建 junction、
写 memory 视图 + 受管块 + opencode 条目)、`refresh`(重算 memory 视图 + 受管块 + opencode 条目)、
`promote` / `promote-memory`(写金库 `shared/`)、以及 `bootstrap`(兼容 / 旧入口——换新机时只往各工具
`skills/` 装加载器 skill;skill 自己也在金库里,这是个鸡生蛋,bootstrap 只打破这个循环,剩下的交给
skill 判断)。A 阶段的 `collect` / `sync` **不在此列**:它们只碰 `<本机>/` 备份区。

---

## 5. 硬闸(不靠自觉)

- **密钥路径永不读取**(`hub/guard.py`)。路径里任何一层组件命中 `secrets` / `auth.json` /
  `.env`(大小写不敏感、按组件整体比对、字面路径与解析后的真实路径两边都查)→ 直接拒绝。
  **不可豁免。** 私密内容留在 `~/.claude/secrets/`,记忆里只写指针。
- **`sensitive: true` 的记忆不入库**,报告里只列名字、不列内容。
- **所有写/删都走 `hub/writer.py` 的 `Writer`**,`--dry-run` 的闸设在**每个写方法里面**,
  不设在调用方 —— 配置式预览的失败模式是"照真的写"(最危险的方向),闸在写函数里的
  失败模式是"什么都不写"。
- **疑似密钥扫描**(`hub/secrets_scan.py`)是**只提醒,不阻断**:它扫刚落进金库的东西并
  打印命中,但**从不**中止、跳过或改变任何一次写入。

---

## 6. 源码地图

| 文件 | 干什么 |
|---|---|
| `cli.py` | 命令入口(A:`collect` / `sync`;C:`promote` / `promote-memory` / `register` / `refresh` / `migrate-schema` / `memory-read`;A/C:`status`(现也报 C 的链接与视图健康);`bootstrap`) |
| `collect/` | 四条提取流水线:`memory` / `skills` / `decl`(插件声明)/ agents 文件 |
| `writer.py` | **唯一写入口** + dry-run 闸 |
| `guard.py` | 密钥路径硬闸(不可豁免) |
| `secrets_scan.py` | 疑似密钥软提醒(只报告) |
| `fslink.py` | (C)目录链接原语 junction/symlink + `is_under`;`remove_dir_link` 只删链接点、绝不误删真目录 |
| `promote.py` | (C)备份区选定 skill → `shared/`:复制、路径边界封死、同名冲突即停 |
| `register.py` | (C)`shared/skills/` 逐个活链进各工具 skill 目录:非破坏、写前完整只读预检、冲突零写入 |
| `status_report.py` | (C)只读报告各工具 skill 链接健康(`ok` / `missing` / `conflict`) |
| `vaultpaths.py` | (C)`shared/skills` 容器边界断言:防经链接逃出金库,promote/register/status 三处共用 |
| `memview.py` | (C)memory 下行视图核心:`shared/memory` 只扫一次、全量 scope 预检,内存里按(设备,工具)切子集,喂给渲染器 |
| `textblock.py` | (C)通用受管块编辑 `<!-- hub:begin -->…<!-- hub:end -->`:无标记追加、一对合法只换块内、格式非法零写入 |
| `opencode_cfg.py` | (C)`opencode.json` 的 `instructions[]` 写入:plan(只读预检)/commit(写)两段,严格 JSON 才改,解析失败一律 refuse 降 warning、不覆盖 |
| `hubconfig.py` | (C)本机指针 `~/.hub/config.toml`(vault/host/hub_root)+ `~/.hub/backups`;`register` 写、`memory-read` 缺 `--vault` 时读 |
| `memread.py` | (C)`memory-read` 核心:只在本机该 tool 视图里查名(拒读越 scope)、读正文、内存展开符号根,不写第二份 |
| `memwire.py` | (C)memory 视图/受管块/opencode 条目的落盘编排:prepare(只读预检+渲染全部目标)→ commit(逐个原子写) |
| `migrate.py` | (C)`vault.toml` schema 版本迁移,当前只支持 v1→v2:只从 version 1 升、且要求全部记忆已是 `[global]` |
| `frontmatter.py` | 记忆 frontmatter 的受控 YAML 子集(认不出来的键**原样带着走**) |
| `snapshot.py` | `git archive HEAD` → 干净的目录树快照 |
| `tomlout.py` | 极简 TOML 写出器(只认 str/bool/int,没见过的形状**抛错**) |
| `vault.py` / `model.py` | 金库与记忆的读取和数据模型 |
| `derive.py` | 重算 `MEMORY.md` 索引 |
| `links.py` / `scope.py` | 符号根 / scope 的校验(`sync` 的 lint 用) |
| `backend.py` | git 后端(pull / commit / push) |
| `schema_md.py` | **`SCHEMA.md` 的正文**——A 与 C 之间唯一的契约 |
| `scaffold_vault.py` | 建库脚手架 |

改 `schema_md.py` 之前先想一遍:加载器的作者只能读到那份文件,**里面写错一句话,
比漏写一句话更糟**。

---

## 7. memory 视图(下行)

memory 走一条与 skill 不同的路:**skill 活链、memory 走上行收集 + 下行只读视图**,
不直连活文件。

**上行(人工闸)**:

    <本机>工具产出 ──A collect──▶ <本机>/claude/memory ──hub promote-memory(人工挑,复制)──▶ shared/memory

`collect` 只把记忆搬进备份区;要进金库的共享池,必须显式跑 `promote-memory --name <n>` 或
`--all`(批量、非 mirror,绝不因源端删了就跟着删)。这一步是人工审阅闸——`shared/memory` 里的
东西默认视为"已过审、可下发给所有工具"。

**下行(生成产物,不进金库)**:`register`(首建)/ `refresh`(shared 变化后重算)从 `shared/memory`
**只扫一次**,按每台设备的 `class`/`projects` 订阅 + 目标 `tool` 做 scope 过滤,产出三样东西:

- `~/.hub/views/<tool>/MEMORY.md`(`tool` = `claude`/`codex`/`opencode`):薄索引,只列
  name/description/scope + 绝对源路径,**本机派生物、不进金库、A 不收集**。
- Claude:`~/.claude/CLAUDE.md` 里一段 `<!-- hub:begin -->…<!-- hub:end -->` 受管块,
  内含 `@~/.hub/views/claude/MEMORY.md` 指针(块外用户内容原样保留)。
- Codex:`~/.codex/AGENTS.md`(或已探测到的活动 `AGENTS.override.md`)同样的受管块,但**内联紧凑
  索引**(无 `@import`,靠内联达成自动发现)。
- opencode:**仅当 `device.toml` 显式设了 `OPENCODE_CONFIG`** 才接(该文件含明文密钥,不因默认
  路径 `~/.config/opencode/opencode.json` 恰好存在就去碰它)。接时把视图路径追加进 `instructions[]`
  (JSON 数组增改,非文本块;解析失败/格式不对 → 拒改,只打印要手工加的条目,不阻断 register/refresh 的其余部分)。

**正文按需读**:视图文件只是索引,不含记忆正文。真要读某条记忆,由随包的 `hub-memory` skill
调 `hub memory-read --tool <claude|codex|opencode> --name <n>`——只解析在**本机该 tool
视图里**出现的名字(拒读越 scope 记忆),读 canonical 内容后在内存里展开符号根,不写第二份、
不改 `shared/`。

**scope v2 语法**:`global` / `class:<名>` / `project:<名>` / `tool:<claude|codex|opencode>`。
`global`/`class:`/`project:` 同属**设备订阅维度**(维度内 OR),`tool:` 是独立维度;两维之间 AND。
`project:<名>` 是**设备订阅条件**(本机 `device.toml` 的 `projects` 含该名才纳入),**不是**
"仅在该工程会话可见"——视图本身是**用户级全局视图**。`global` 必须独占,不与任何标签混用。
金库 `vault.toml` 的 `version` 字段随这套语法升到 `2`;从 v1 库升级用 `migrate-schema --to 2`
(见 §4,只从 version 1 升、且要求全部记忆已是 `[global]`,否则列清单拒绝)。

**sync 不越界、refresh 显式**:`sync`(A)只碰金库本身(pull/lint/derive/commit/push),**绝不**
顺手重算这些视图/受管块/opencode 条目;`shared/` 变化后要看到效果,必须显式跑 `hub refresh`,
或用 `sync --refresh` 串联(成功后调 `refresh` 并传播其返回码)。

---

## 插件：shared 活源 + market-of-one

自有插件的稳态活源位于 `<vault>/shared/plugins/<name>/`；每个插件继续保留自己的 `.git`、remote 和提交历史，
父金库同时跟踪除嵌套 `.git` 外的源码文件。`~/.claude/plugins-dev` 只是一轮迁移输入，cutover 完成后不再是活源。

每个插件自带 market-of-one，稳定身份为 `<name>@<name>`。`shared/plugins/manifest.toml` 声明插件及适配平台；
`<host>/device.toml` 的 `[plugins.claude].enabled` / `[plugins.codex].enabled` 是本机分平台允许列表。

- `hub register --vault <v> --host <h>`：注册全部适配市场，并按 device 允许列表收敛安装/启用状态。
- `hub refresh --vault <v> --host <h>`：只刷新已经安装且已显式 bump+commit 的插件；不替用户改版本或源码仓。
- `hub status --vault <v> --host <h> --check`：只读检查 source、启用态、仓状态和本机刷新基线。
- `hub migrate-plugins ...`（phase1）/ `hub cutover-plugins ...`（phase2）/
  `hub retire-plugin-sources ...`（phase3）：一次性迁移的三段式。phase1 只复制+induct **绝不删源**；
  phase2 只官方 CLI 平台切换；phase3 平台切换验证通过后才退役旧源（全量预检，任一旧引用/新身份未就位→零删除）。
  严格按 `docs/runbooks/2026-07-hub-plugin-cutover.md` 的三个人工检查点执行。

平台 marketplace、安装、启用和卸载全部通过 Claude/Codex 官方 CLI；hub 不直接修改平台 cache、
installed_plugins.json、known_marketplaces.json 或 Codex config.toml。本机刷新基线保存在
`~/.hub/plugin-state.toml`，它是运行态，不进金库。
