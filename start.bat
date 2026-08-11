@echo off
chcp 65001 >nul 2>&1
title Shop Query - 一键启动
setlocal EnableDelayedExpansion

:: ============================================================
::  Shop Query 一键启动脚本 (Windows 版本)
::  启动顺序: Docker 基础设施 → 后端 (FastAPI) → 前端 (Vite)
:: ============================================================

set "ROOT_DIR=%~dp0"
set "DOCKER_DIR=%ROOT_DIR%docker"
set "FRONTEND_DIR=%ROOT_DIR%frontend"
set "LOGS_DIR=%ROOT_DIR%logs"
set "PID_DIR=%ROOT_DIR%.pids"

:: 创建日志目录
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"
if not exist "%PID_DIR%" mkdir "%PID_DIR%"

set "BACKEND_LOG=%LOGS_DIR%\backend.log"
set "FRONTEND_LOG=%LOGS_DIR%\frontend.log"

:: 端口配置
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

:: ----------------------------------------------------------
::  颜色设置 (Windows 10+)
:: ----------------------------------------------------------
set "GREEN=[32m"
set "RED=[31m"
set "YELLOW=[33m"
set "BLUE=[34m"
set "NC=[0m"

:: 辅助函数: 输出信息
call :log_info "========================================"
call :log_info "  Shop Query - 一键启动"
call :log_info "========================================"
echo.

:: ============================================================
::  第 0 步: 环境检查
:: ============================================================
call :log_step "[0/4] 环境检查..."

:: 检查 Docker
docker --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    call :log_error "Docker 未安装，请先安装 Docker Desktop"
    pause
    exit /b 1
)

:: 检查 docker compose
docker compose version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    call :log_error "Docker Compose 插件未安装"
    pause
    exit /b 1
)

:: 检查 uv
where uv >nul 2>&1
if %ERRORLEVEL% neq 0 (
    call :log_error "uv 未安装，请先安装 uv (https://github.com/astral-sh/uv)"
    pause
    exit /b 1
)

:: 检查 pnpm
where pnpm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    call :log_error "pnpm 未安装，请先安装 pnpm (npm install -g pnpm)"
    pause
    exit /b 1
)

call :log_info "环境检查通过"

:: ============================================================
::  第 1 步: 启动 Docker 基础设施
:: ============================================================
echo.
call :log_step "[1/4] 启动 Docker 基础设施..."

:: 检查 Docker 引擎是否运行
docker info >nul 2>&1
if %ERRORLEVEL% equ 0 (
    call :log_info "Docker 已运行"
) else (
    call :log_warn "Docker 引擎未运行，尝试启动 Docker Desktop..."

    :: 尝试常见安装路径
    set "DOCKER_EXE="
    if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        set "DOCKER_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    ) else if exist "%ProgramFiles(x86)%\Docker\Docker\Docker Desktop.exe" (
        set "DOCKER_EXE=%ProgramFiles(x86)%\Docker\Docker\Docker Desktop.exe"
    ) else if exist "%LOCALAPPDATA%\Docker\Docker Desktop.exe" (
        set "DOCKER_EXE=%LOCALAPPDATA%\Docker\Docker Desktop.exe"
    )

    if defined DOCKER_EXE (
        start "" "!DOCKER_EXE!"
    ) else (
        start "" "Docker Desktop"
    )

    call :log_info "Docker Desktop 启动中，等待引擎就绪..."
    set "dw=0"
    :dw_loop
    if !dw! geq 60 (
        call :log_error "Docker 引擎 60 秒内未就绪，请手动启动后重试"
        pause
        exit /b 1
    )
    timeout /t 3 /nobreak >nul
    set /a dw+=3
    docker info >nul 2>&1
    if %ERRORLEVEL% neq 0 goto dw_loop
    call :log_info "Docker 引擎已就绪"
)

:: 启动 Docker Compose 服务
pushd "%DOCKER_DIR%"
docker compose up -d --build
if %ERRORLEVEL% neq 0 (
    call :log_error "Docker Compose 启动失败，请检查 docker/docker-compose.yaml"
    popd
    pause
    exit /b 1
)
popd
call :log_info "Docker 容器已启动"

:: 等待关键服务就绪
call :wait_for_port "localhost" "3306" "30" "MySQL"
call :wait_for_port "localhost" "9201" "60" "Elasticsearch"
call :wait_for_port "localhost" "6333" "30" "Qdrant"
call :wait_for_port "localhost" "8081" "60" "Embedding Service"
call :wait_for_port "localhost" "6379" "30" "Redis"

:: ============================================================
::  第 2 步: 安装/检查依赖
:: ============================================================
echo.
call :log_step "[2/4] 检查项目依赖..."

:: 检查后端依赖
if not exist "%ROOT_DIR%\.venv" (
    call :log_warn "后端虚拟环境不存在，正在创建..."
    pushd "%ROOT_DIR%"
    uv sync
    if %ERRORLEVEL% neq 0 (
        call :log_error "后端依赖安装失败"
        popd
        pause
        exit /b 1
    )
    popd
)
call :log_info "后端依赖已就绪"

:: 检查前端依赖
if not exist "%FRONTEND_DIR%\node_modules" (
    call :log_warn "前端依赖未安装，正在安装..."
    pushd "%FRONTEND_DIR%"
    pnpm install
    if %ERRORLEVEL% neq 0 (
        call :log_error "前端依赖安装失败"
        popd
        pause
        exit /b 1
    )
    popd
)
call :log_info "前端依赖已就绪"

:: ============================================================
::  第 3 步: 启动后端
:: ============================================================
echo.
call :log_step "[3/4] 启动后端 FastAPI 服务 (端口 %BACKEND_PORT%)..."

:: 生成后端启动脚本（避免 start 命令中的引号和转义问题）
(
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title Shop Query - Backend
    echo cd /d "%ROOT_DIR%"
    echo echo [Backend] 正在启动后端服务...
    echo uv run uvicorn main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload
) > "%PID_DIR%\start_backend.cmd"

start "Shop Query - Backend" cmd /k "%PID_DIR%\start_backend.cmd"

:: 等待后端端口就绪
call :wait_for_port "localhost" "%BACKEND_PORT%" "30" "后端服务"

:: ============================================================
::  第 4 步: 启动前端
:: ============================================================
echo.
call :log_step "[4/4] 启动前端 Vite 开发服务 (端口 %FRONTEND_PORT%)..."

:: 生成前端启动脚本（避免 start 命令中的引号和转义问题）
(
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo title Shop Query - Frontend
    echo cd /d "%FRONTEND_DIR%"
    echo echo [Frontend] 正在启动前端服务...
    echo pnpm dev
) > "%PID_DIR%\start_frontend.cmd"

start "Shop Query - Frontend" cmd /k "%PID_DIR%\start_frontend.cmd"

:: 等待前端端口就绪
call :wait_for_port "localhost" "%FRONTEND_PORT%" "30" "前端服务"

:: ============================================================
::  启动完成
:: ============================================================
echo.
call :log_info "========================================"
call :log_info "  所有服务已启动!"
call :log_info "========================================"
echo.
call :log_info "服务地址:"
echo    前端:          http://localhost:%FRONTEND_PORT%
echo    后端 API:      http://localhost:%BACKEND_PORT%
echo    API 文档:      http://localhost:%BACKEND_PORT%/docs
echo    Kibana:        http://localhost:5601
echo    Qdrant:        http://localhost:6333/dashboard
echo    RedisInsight:  http://localhost:8001
echo.
echo  Docker 服务:
echo    MySQL:         localhost:3306
echo    Elasticsearch: localhost:9201
echo    Qdrant:        localhost:6333
echo    Embedding:     localhost:8081
echo    Redis:         localhost:6379
echo    RedisInsight:  localhost:8001
echo.
call :log_info "日志文件:"
echo    后端: %BACKEND_LOG%
echo    前端: %FRONTEND_LOG%
echo.
call :log_warn "按任意键停止所有服务..."
pause >nul

:: ============================================================
::  停止所有服务
:: ============================================================
echo.
call :log_step "正在停止服务..."

:: 关闭后端和前端窗口 (通过窗口标题)
taskkill /FI "WINDOWTITLE eq Shop Query - Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Shop Query - Frontend*" /F >nul 2>&1

:: 补充: 直接杀占用端口的进程 (以防窗口标题不匹配)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT%.*LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT%.*LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: 停止 Docker 服务
pushd "%DOCKER_DIR%"
docker compose stop
popd

call :log_info "所有服务已停止"
pause
exit /b 0

:: ============================================================
::  辅助函数
:: ============================================================

:log_info
    echo [%GREEN%INFO%NC%] %~1
    goto :eof

:log_warn
    echo [%YELLOW%WARN%NC%] %~1
    goto :eof

:log_error
    echo [%RED%ERROR%NC%] %~1
    goto :eof

:log_step
    echo [%BLUE%STEP%NC%] %~1
    goto :eof

:wait_for_port
    :: 参数: host, port, timeout_seconds, service_name
    set "_host=%~1"
    set "_port=%~2"
    set "_timeout=%~3"
    set "_name=%~4"
    set "_elapsed=0"

    call :log_info "等待 %_name% (%_host%:%_port%) 就绪..."

    :wait_loop
    :: 使用 PowerShell 测试端口连接
    powershell -Command "$c = New-Object System.Net.Sockets.TcpClient; try { $c.Connect('%_host%', %_port%); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        call :log_info "%_name% 已就绪"
        goto :eof
    )

    if %_elapsed% geq %_timeout% (
        call :log_error "%_name% 在 %_timeout% 秒内未就绪"
        goto :eof
    )

    timeout /t 1 /nobreak >nul
    set /a _elapsed+=1
    goto wait_loop
