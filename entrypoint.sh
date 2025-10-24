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

# 将拉取逻辑写成独立脚本（而非函数），确保cron可调用
cat > /usr/local/bin/pull_and_update << 'EOF'
#!/bin/sh
set -e

REPO_DIR="/app/repo"
TEMP_REPO_DIR="/app/repo_temp"

echo "开始拉取最新代码..."

# 首次启动：用临时目录克隆（避开挂载的config.yaml）
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "首次启动，用临时目录克隆仓库..."
    rm -rf "$TEMP_REPO_DIR"
    mkdir -p "$TEMP_REPO_DIR"
    git clone "$REPO_URL" "$TEMP_REPO_DIR" || { echo "克隆仓库失败"; exit 1; }

    mkdir -p "$REPO_DIR"
    cp -r "$TEMP_REPO_DIR"/* "$REPO_DIR/" 2>/dev/null || true
    cp -r "$TEMP_REPO_DIR"/.git "$REPO_DIR/"
    rm -rf "$TEMP_REPO_DIR"
else
    # 非首次启动：直接拉取更新
    echo "非首次启动，拉取更新..."
    cd "$REPO_DIR" || exit 1
    git pull || { echo "拉取代码失败"; exit 1; }
fi

# 安装依赖
cd "$REPO_DIR" || exit 1
if [ -f "requirements.txt" ]; then
    echo "安装依赖..."
    pip install --no-cache-dir -r requirements.txt || { echo "依赖安装失败"; exit 1; }
fi

echo "代码拉取和依赖更新完成"
EOF

# 给脚本添加执行权限
chmod +x /usr/local/bin/pull_and_update

# 初始拉取代码（容器启动时执行一次）
pull_and_update

# 配置定时任务（修正语法：去掉多余引号，调用独立脚本）
PULL_CRON=${PULL_CRON:-"0 18 * * *"}  # 默认定时拉取：每天18点
echo "配置代码拉取定时任务：$PULL_CRON"
echo "配置程序执行定时任务：$CRON_SCHEDULE"

# 生成 crontab 配置（注意：时间表达式和命令之间无引号，调用独立脚本）
CRON_JOBS=$(cat <<EOF
# 定时拉取代码（调用独立脚本，而非函数）
$PULL_CRON /usr/local/bin/pull_and_update >> /var/log/cron/pull.log 2>&1

# 定时执行主程序
$CRON_SCHEDULE /usr/local/bin/python -u $REPO_DIR/src/main.py >> /app/logs/main.log 2>&1
EOF
)

# 写入 crontab
echo "$CRON_JOBS" | crontab -

# 启动 cron 服务
echo "启动定时任务服务..."
# 启动 cronie 服务，保持前台运行
crond -f -l 8