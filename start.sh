#!/usr/bin/env bash
set -e

# 1) 启动 WebSocket Server (后台)
python run_server.py &
SERVER_PID=$!

# 2) 用 /dev/tcp 等待端口就绪（最多 30 秒）
echo "⏳ Waiting for server on $PORT ..."
for i in {1..30}; do
  (echo > /dev/tcp/127.0.0.1/$PORT) >/dev/null 2>&1 && break
  sleep 1
done

# 3) 生成容器内环回地址并启动 Telegram Bot
export VWS_URL="ws://127.0.0.1:${PORT}/client-ws"
python bot/telegram/telegram_bot.py --token "$TELEGRAM_BOT_TOKEN" --ws-url "$VWS_URL" &

# 如果你跑 Discord，把上一行换成：
# python bot/discord/discord_bot.py --token "$DISCORD_BOT_TOKEN" --ws-url "$VWS_URL" &

# 4) 捕获 SIGTERM，优雅退出
trap 'kill -TERM $SERVER_PID 2>/dev/null' TERM

# 5) 阻塞到主进程退出
wait $SERVER_PID
