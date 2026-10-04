@echo off
chcp 65001 >nul
title SteamUnlock 密钥提取
echo.
echo ============================================
echo   SteamUnlock 密钥提取工具
echo ============================================
echo.
echo 正在启动（需要管理员权限）...
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 正在请求管理员权限...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo [OK] 已获得管理员权限
echo.
echo 正在运行扫描脚本...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0找密钥.ps1"

echo.
echo 脚本已结束。
pause
