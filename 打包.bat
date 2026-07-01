@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title Pack AI-CLI Migration Bundle (Claude Code + Codex)
echo Packing Claude Code + Codex migration bundle to Desktop, please wait...
echo.
py -3 "%~dp0pack_migration.py" %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
    echo [OK] Done. You can close this window.
) else (
    echo [FAILED] Exit code %RC%. Please screenshot the errors above and send to me.
)
echo.
pause
