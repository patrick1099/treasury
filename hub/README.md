# hub —— 把本机 AI 工具的家当收进一个 git 金库,再活链回各工具

`hub` 目前有两个**边界明确**的阶段,都在这个仓库里:

- **A 提取器(`collect` / `sync`)**:读本机 Claude Code / Codex 的配置与产出,**只**收进金库的
  **备份区**。**绝不把内容写回工具地盘,也不写 `shared/`。**
- **C 注册器(`promote` / `register` / `status`,C 阶段 Plan 1——只做 skill)**:由用户**显式调用**。
  `promote` 把选定 skill 从备份区**复制**进 `shared/`;`register` 把 `shared/` 的 skill **逐个 junction**
  链进 Claude / Codex / opencode 的 skill 目录(改一处三家实时生效)。memory 视图与 plugin 见后续计划。

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
| **C 注册器** | 判断题;skill-loop(`register`/`promote`/`status`)已在本包,memory 视图 / plugin 见后续计划 | `shared/`、各工具 skill 目录(经用户显式调用 + 安全闸) |

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
| `register` | 把 `shared/skills/` 逐个**活链**进各工具(Claude `~/.claude/skills`、Codex/opencode `~/.agents/skills`);改一处三家实时生效;非破坏,冲突即停不写 | 否 |
| `status` | 金库的 `git status --porcelain`,再附各工具的 skill 链接健康(`ok` / `missing` / `conflict`) | 否 |
| `bootstrap` | (兼容 / 旧入口)换新机时把金库里的加载器 skill 装进各工具,然后退场 | 否 |
| `hub-scaffold`(`python -m hub.scaffold_vault`) | 建金库 / 把一台新设备加进已有金库 | 否 |

- `collect` / `promote` / `register` / `bootstrap` 都支持 **`--dry-run`**(一个字节都不落盘,只打印会写什么);
  `collect` / `bootstrap` 另有 **`--yes`**(不询问,直接执行,含删除)。
- `scaffold` 的参数是**两个位置参数** + `--force` / `--dry-run`:
  `py -3 -m hub.scaffold_vault <金库目录> <设备名>`。

**会写金库以外地方的命令(都非自动、都过安全闸)**:`register`(在各工具 skill 目录建 junction)、
`promote`(写金库 `shared/`)、以及 `bootstrap`(兼容 / 旧入口——换新机时只往各工具 `skills/` 装
加载器 skill;skill 自己也在金库里,这是个鸡生蛋,bootstrap 只打破这个循环,剩下的交给 skill 判断)。
A 阶段的 `collect` / `sync` **不在此列**:它们只碰 `<本机>/` 备份区。

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
| `cli.py` | 命令入口(A:`collect` / `sync` / `status`;C:`promote` / `register`;`bootstrap`) |
| `collect/` | 四条提取流水线:`memory` / `skills` / `decl`(插件声明)/ agents 文件 |
| `writer.py` | **唯一写入口** + dry-run 闸 |
| `guard.py` | 密钥路径硬闸(不可豁免) |
| `secrets_scan.py` | 疑似密钥软提醒(只报告) |
| `fslink.py` | (C)目录链接原语 junction/symlink + `is_under`;`remove_dir_link` 只删链接点、绝不误删真目录 |
| `promote.py` | (C)备份区选定 skill → `shared/`:复制、路径边界封死、同名冲突即停 |
| `register.py` | (C)`shared/skills/` 逐个活链进各工具 skill 目录:非破坏、写前完整只读预检、冲突零写入 |
| `status_report.py` | (C)只读报告各工具 skill 链接健康(`ok` / `missing` / `conflict`) |
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
