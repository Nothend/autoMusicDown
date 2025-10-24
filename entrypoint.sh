#!/bin/sh
set -e  # 遇到错误立即退出

# 定义最终代码目录和临时克隆目录
REPO_DIR="/app/repo"
TEMP_REPO_DIR="/app/repo_temp"  # 临时目录（无挂载，确保空）

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

    # 首次启动：用临时目录克隆（避开挂载的config.yaml）
    if [ ! -d "$REPO_DIR/.git" ]; then
        echo "首次启动，用临时目录克隆仓库..."
        # 确保临时目录为空并克隆
        rm -rf "$TEMP_REPO_DIR"  # 清空旧临时目录（如有）
        mkdir -p "$TEMP_REPO_DIR"
        git clone "$REPO_URL" "$TEMP_REPO_DIR" || { echo "克隆仓库失败"; exit 1; }

        # 确保最终代码目录存在，将临时目录代码复制到最终目录（排除config.yaml，避免覆盖挂载文件）
        mkdir -p "$REPO_DIR"
        cp -r "$TEMP_REPO_DIR"/* "$REPO_DIR/" 2>/dev/null || true  # 忽略config.yaml覆盖警告
        cp -r "$TEMP_REPO_DIR"/.git "$REPO_DIR/"  # 复制.git目录（后续拉取用）
        rm -rf "$TEMP_REPO_DIR"  # 复制完成后删除临时目录
    else
        # 非首次启动：直接在最终目录拉取更新（.git存在，无需空目录）
        echo "非首次启动，在最终目录拉取更新..."
        cd "$REPO_DIR" || exit 1
        git pull || { echo "拉取代码失败"; exit 1; }
    fi

    # 进入最终代码目录安装依赖
    cd "$REPO_DIR" || exit 1
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

# 生成 crontab 配置（执行路径为最终代码目录）
CRON_JOBS=$(cat <<EOF
# 定时拉取代码并更新依赖（调用pull_and_update函数）
$PULL_CRON /bin/sh -c 'pull_and_update' >> /var/log/cron/pull.log 2>&1

# 定时执行主程序（最终代码目录下的src/main.py）
$CRON_SCHEDULE /usr/local/bin/python -u $REPO_DIR/src/main.py >> /app/logs/main.log 2>&1
EOF
)

# 写入 crontab
echo "$CRON_JOBS" | crontab -

# 启动 cron 服务（前台运行以保持容器活跃）
echo "启动定时任务服务..."
crond -f -l 8  # -f 前台运行，-l 8 日志级别