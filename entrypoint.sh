#!/bin/sh
set -e  # 遇到错误立即退出

# 检查必要环境变量
if [ -z "$REPO_URL" ]; then
    echo "错误：未设置 REPO_URL 环境变量（仓库地址）"
    exit 1
fi
if [ -z "$CRON_SCHEDULE" ]; then
    echo "错误：未设置 CRON_SCHEDULE 环境变量（执行任务的cron表达式）"
    exit 1
fi

# 拉取代码并安装依赖的函数
pull_and_update() {
    echo "开始拉取最新代码..."
    cd /app || exit 1  # 确保在工作目录

    # 首次启动克隆仓库，后续拉取更新
    if [ ! -d ".git" ]; then
        git clone "$REPO_URL" . || { echo "克隆仓库失败"; exit 1; }
    else
        git pull || { echo "拉取代码失败"; exit 1; }
    fi

    # 安装/更新依赖
    if [ -f "requirements.txt" ]; then
        echo "安装依赖..."
        pip install --no-cache-dir -r requirements.txt || { echo "依赖安装失败"; exit 1; }
    else
        echo "未找到 requirements.txt，跳过依赖安装"
    fi

    echo "代码拉取和依赖更新完成"
}

# 初始拉取代码（容器启动时执行一次）
pull_and_update

# 配置定时任务（拉取代码默认每天18点，执行程序按CRON_SCHEDULE）
PULL_CRON=${PULL_CRON:-"0 18 * * *"}  # 默认定时拉取：每天晚上6点（18:00）
echo "配置代码拉取定时任务：$PULL_CRON"
echo "配置程序执行定时任务：$CRON_SCHEDULE"

# 生成 crontab 配置
CRON_JOBS=$(cat <<EOF
# 定时拉取代码并更新依赖
$PULL_CRON /bin/sh -c 'cd /app && pull_and_update' >> /var/log/cron/pull.log 2>&1

# 定时执行主程序
$CRON_SCHEDULE /usr/local/bin/python -u /app/src/main.py >> /app/logs/main.log 2>&1
EOF
)

# 写入 crontab
echo "$CRON_JOBS" | crontab -

# 启动 cron 服务（前台运行以保持容器活跃）
echo "启动定时任务服务..."
crond -f -l 8  # -f 前台运行，-l 8 日志级别