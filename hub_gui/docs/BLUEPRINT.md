# hub-gui 蓝图

## 一句话

hub-gui 是在本机以只读矩阵查看 `hub inventory --json` 资产的 Python 小应用：行是资产（plugin / skill / memory），列是 harness（claude / codex / opencode / dsh），每个单元格展示 desired / actual / health / control / detail。

## 功能行为

- 启动后由 `app.py` 在 `127.0.0.1:<随机端口>` 起 uvicorn，再用 pywebview 打开本地页面。
- 前端 `fetch('/api/inventory')` 获取规范化数据并渲染矩阵。
- 支持 harness 筛选、资产类型筛选、名称/ID/路径搜索。
- 单元格用颜色表达 health：ok 绿、missing 黄、conflict 红、orphan 橙、unknown 灰。
- 对 Claude/Codex 插件内 skill 显示“由插件整体控制”（control=plugin）。
- memory 显示只读标记。

## 边界

- D1 只读：不提供真实开关，不调用 `hub toggle`。
- 本应用不直接修改任何平台配置；所有数据来自 `hub inventory --json`。
- `core` 只做 subprocess/JSON 边界转换，不包含展示矩阵或业务判断。
- `api` 只做 HTTP↔core 翻译，并将 `web/` 作为静态目录挂载。
- harness 单元格缺失表示该平台对该资产不适用，前端显示“—”。

## 硬约束（可移植架构约束）

- 逻辑与 UI/框架解耦：业务逻辑全部位于 `core/`，可由 pytest 直接构造输入测试。
- 逻辑层不依赖 FastAPI、pywebview 或浏览器；`core` 不读全局单用户状态。
- 通信走标准 HTTP/JSON，不使用 pywebview 专有 JS 桥。
- 前端零构建：原生 HTML/CSS/JS + CDN CSS，无 npm/React/Vue。
- 未来换交付层（部署 FastAPI、换 UI 框架）时 `core` 不动。
