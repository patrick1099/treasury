# hub-gui

只读展示 hub 资产 × harness 矩阵的 Python 桌面小应用。D1 阶段只读：
通过 `hub inventory --json` 拉取数据，不调用 `hub toggle`。

## 架构约束（vibe-apps）

五层：core(纯逻辑可 pytest, 对"谁"无状态) / api(FastAPI 薄适配) / web(HTML+fetch) / app.py(拼装) / pywebview(壳)。

逻辑只放 core；api 只做 HTTP↔core 翻译；web 不含业务逻辑。

前端默认原生 HTML/CSS/JS + CDN CSS，零构建无 npm；通信走 HTTP，不用 pywebview 专有桥。

D1 只读铁律：本目录任何代码不得调用 `hub toggle`；只允许调用 `hub inventory --json`。
