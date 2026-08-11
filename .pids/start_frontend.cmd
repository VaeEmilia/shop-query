@echo off
chcp 65001 >nul 2>&1
title Shop Query - Frontend
cd /d "F:\code\ai\shop-query\frontend"
echo [Frontend] 正在启动前端服务...
pnpm dev
