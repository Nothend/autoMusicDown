#!/bin/sh
set -e

log_time() { date +"%Y-%m-%d %H:%M:%S %Z"; }

# 执行调度：默认每天 20-23 点及 0 点整点各一次
CRON_SCHEDULE="${CRON_SCHEDULE:-0 20-23,0 * * *}"
# 可选：容器启动即先跑一次（默认关闭，避免每次重启都触发一轮下载）
RUN_ON_START="${RUN_ON_START:-false}"

echo "[$(log_time)] 配置程序执行定时任务：$CRON_SCHEDULE"

if [ "$RUN_ON_START" = "true" ]; then
    echo "[$(log_time)] RUN_ON_START=true，立即执行一次同步"
    python -u /app/src/main.py || echo "[$(log_time)] 首次执行返回非零，忽略并继续定时任务"
fi

# 写入 crontab 并启动 crond：
# - cd /app 固定工作目录；
# - 将任务 stdout/stderr 重定向到 PID 1(crond) 的输出，使 docker logs 能看到每轮执行日志。
echo "$CRON_SCHEDULE cd /app && /usr/local/bin/python -u /app/src/main.py > /proc/1/fd/1 2>/proc/1/fd/2" | crontab -

echo "[$(log_time)] 启动 crond..."
exec crond -f -l 2
