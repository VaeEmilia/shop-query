@echo off
chcp 65001 >nul 2>&1
title Shop Query - 停止所有服务

:: ============================================================
::  Shop Query 一键停止脚本
::  停止顺序: 前端 → 后端 → Docker 基础设施
:: ============================================================

set "ROOT_DIR=%~dp0"
set "DOCKER_DIR=%ROOT_DIR%docker"

echo.
echo  ============================================
echo    Shop Query - 停止所有服务
echo  ============================================
echo.

:: ----------------------------------------------------------
::  停止前端和后端进程
:: ----------------------------------------------------------
echo [1/2] 停止应用服务...

:: 通过窗口标题关闭
taskkill /FI "WINDOWTITLE eq Shop Query - Backend*" /F >nul 2>&1 && (
    echo       后端服务已停止 ✓
) || (
    echo       后端服务未运行
)

taskkill /FI "WINDOWTITLE eq Shop Query - Frontend*" /F >nul 2>&1 && (
    echo       前端服务已停止 ✓
) || (
    echo       前端服务未运行
)

:: 补充: 直接杀占用端口的进程 (以防窗口标题不匹配)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173.*LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo       应用服务检查完毕 ✓

:: ----------------------------------------------------------
::  停止 Docker 基础设施
:: ----------------------------------------------------------
echo.
echo [2/2] 停止 Docker 基础设施服务...

docker info >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo       Docker 未运行，跳过
) else (
    pushd "%DOCKER_DIR%"
    docker compose stop
    if %ERRORLEVEL% equ 0 (
        popd
        echo       Docker 服务已停止 ✓
    ) else (
        popd
        echo [警告] Docker 服务停止时出现问题
    )
)

echo.
echo  ============================================
echo    所有服务已停止
echo  ============================================
echo.
pause
