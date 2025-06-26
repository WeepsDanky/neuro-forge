#!/usr/bin/env bash
set -e

# 1) 启动 WebSocket Server（前台）
python run_server.py &
SERVER_PID=$!

# 2) 等端口就绪（最多 180 秒）
echo "⏳ Waiting for server on $PORT ..."
for i in {1..180}; do
  nc -z 127.0.0.1 "$PORT" && break
  sleep 1
done

# 3) 启动 Telegram Bot（后台）
python bot/telegram/run_telegram_bot.py &

# 4) 捕获关机信号，优雅退出
trap 'echo "Received SIGTERM"; kill -TERM $SERVER_PID 2>/dev/null; wait $SERVER_PID' TERM

# 5) 阻塞在前台进程
wait $SERVER_PID
