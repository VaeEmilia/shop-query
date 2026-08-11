#!/bin/bash
# Redis Stack 启动脚本：同时启动 Redis 服务器和 RedisInsight Web UI

set -e

# 启动 Redis 服务器（后台）
redis-stack-server --appendonly yes &
REDIS_PID=$!

# 等待 Redis 就绪
sleep 3

# 启动 RedisInsight
cd /opt/redis-stack
export RI_SERVE_STATICS=1
export RI_APP_PORT=8001
export NODE_ENV=production
export RI_APP_FOLDER_ABSOLUTE_PATH=/redisinsight

/opt/redis-stack/nodejs/bin/node -r /opt/redis-stack/share/redisinsight/api/node_modules/dotenv/config /opt/redis-stack/share/redisinsight/api/dist/src/main.js dotenv_config_path=/opt/redis-stack/share/redisinsight/.env &
INSIGHT_PID=$!

# 捕获退出信号，优雅关闭两个进程
cleanup() {
    echo "Shutting down..."
    kill $REDIS_PID $INSIGHT_PID 2>/dev/null || true
    wait
    exit 0
}
trap cleanup SIGTERM SIGINT

# 等待任一进程退出
while kill -0 $REDIS_PID 2>/dev/null && kill -0 $INSIGHT_PID 2>/dev/null; do
    sleep 1
done

# 如果有进程退出，杀掉另一个
kill $REDIS_PID $INSIGHT_PID 2>/dev/null || true
wait
