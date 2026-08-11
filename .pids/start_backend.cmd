@echo off
chcp 65001 >nul 2>&1
title Shop Query - Backend
cd /d "F:\code\ai\shop-query\"
echo [Backend] 正在启动后端服务...
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
