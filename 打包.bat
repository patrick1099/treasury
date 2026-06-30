@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title 一键打包迁移包 (Claude Code + Codex)
echo 正在打包 Claude Code + Codex 迁移包到桌面,请稍候...
echo.
py -3 "%~dp0pack_migration.py" %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
    echo 打包成功。可以关闭此窗口。
) else (
    echo 打包失败,退出码 %RC%。请把上面的红字/报错截图发我。
)
echo.
pause
