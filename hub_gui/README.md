# hub-gui

本机 GUI：查看 hub/treasury-vault 的 skill、plugin、memory 注入到
Claude / Codex / opencode / dsh 的矩阵，并手动开/关。

## 启动

```bash
cd /c/Users/<user>/treasury/hub_gui
py -3 -m pip install -r requirements.txt

# 开发：浏览器访问
py -3 -m uvicorn api.server:app --reload

# 桌面窗口
py -3 app.py
```

## 依赖

- FastAPI
- uvicorn
- pywebview
- （测试额外需要 httpx）

## 结构

```text
core/   调 hub CLI，无业务逻辑
api/    FastAPI：GET /api/inventory、POST /api/toggle
web/    原生 HTML/CSS/JS + Pico.css，零构建
app.py  uvicorn + pywebview
tests/  pytest
docs/BLUEPRINT.md
```

## 已实现

- D0：`hub inventory --json` / `hub toggle`（CLI 地基）
- D1：只读矩阵 GUI
- D2：GUI 接入手动开关
