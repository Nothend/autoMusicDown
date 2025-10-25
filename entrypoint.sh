#!/bin/sh
set -e  # 遇到错误立即退出

# 定义最终代码目录和临时克隆目录
REPO_DIR="/app/repo"
TEMP_REPO_DIR="/app/repo_temp"  # 临时目录（无挂载，确保空）

# 校验cron表达式格式的函数
validate_cron() {
    local cron_expr="$1"
    # 校验5个字段的基本格式（简化版）
    if ! echo "$cron_expr" | grep -qE '^[0-9*\/,-]+[[:space:]]{1,}[0-9*\/,-]+[[:space:]]{1,}[0-9*\/,-]+[[:space:]]{1,}[0-9*\/,-]+[[:space:]]{1,}[0-9*\/,-]+$'; then
        echo "无效的cron表达式格式：$cron_expr"
        echo "正确格式示例：0 18 * * *（5个字段，空格分隔，支持* / , -）"
        return 1
    fi

    local fields=($cron_expr)
    local min="${fields[0]}"
    local hour="${fields[1]}"
    local dom="${fields[2]}"
    local month="${fields[3]}"
    local dow="${fields[4]}"

    # 验证分钟（简化正则，去掉嵌套）
    if ! echo "$min" | grep -qE '^(\*|[0-5]?[0-9](-[0-5]?[0-9])?(\/[0-9]+)?(,[0-5]?[0-9](-[0-5]?[0-9])?(\/[0-9]+)?)*)$'; then
        echo "分钟字段无效：$min（范围0-59，支持* / , -）"
        return 1
    fi

    # 验证小时（简化）
    if ! echo "$hour" | grep -qE '^(\*|[01]?[0-9]|2[0-3](-[01]?[0-9]|2[0-3])?(\/[0-9]+)?(,[01]?[0-9]|2[0-3](-[01]?[0-9]|2[0-3])?(\/[0-9]+)?)*)$'; then
        echo "小时字段无效：$hour（范围0-23，支持* / , -）"
        return 1
    fi

    # 验证日期（简化）
    if ! echo "$dom" | grep -qE '^(\*|[1-9]|[12][0-9]|3[01](-[1-9]|[12][0-9]|3[01])?(\/[0-9]+)?(,[1-9]|[12][0-9]|3[01](-[1-9]|[12][0-9]|3[01])?(\/[0-9]+)?)*)$'; then
        echo "日期字段无效：$dom（范围1-31，支持* / , -）"
        return 1
    fi

    # 验证月份（简化）
    if ! echo "$month" | grep -qE '^(\*|[1-9]|1[0-2](-[1-9]|1[0-2])?(\/[0-9]+)?(,[1-9]|1[0-2](-[1-9]|1[0-2])?(\/[0-9]+)?)*)$'; then
        echo "月份字段无效：$month（范围1-12，支持* / , -）"
        return 1
    fi

    # 验证星期（简化）
    if ! echo "$dow" | grep -qE '^(\*|[0-6](-[0-6])?(\/[0-9]+)?(,[0-6](-[0-6])?(\/[0-9]+)?)*)$'; then
        echo "星期字段无效：$dow（范围0-6，支持* / , -）"
        return 1
    fi

    return 0
}

# 检查必要环境变量
if [ -z "$REPO_URL" ]; then
    echo "错误：未设置 REPO_URL 环境变量（仓库地址）"
    exit 1
fi
if [ -z "$CRON_SCHEDULE" ]; then
    echo "错误：未设置 CRON_SCHEDULE 环境变量（执行任务的cron表达式）"
    exit 1
fi

# 验证CRON_SCHEDULE格式
if ! validate_cron "$CRON_SCHEDULE"; then
    echo "错误：CRON_SCHEDULE 格式无效"
    exit 1
fi
# 处理PULL_CRON默认值并验证格式
PULL_CRON=${PULL_CRON:-"0 18 * * *"}  # 默认定时拉取：每天18点
if ! validate_cron "$PULL_CRON"; then
    echo "错误：PULL_CRON 格式无效"
    exit 1
fi

# 将拉取逻辑写成独立脚本（用 EOF 而非 'EOF'，允许变量展开）
cat > /usr/local/bin/pull_and_update << EOF  # 关键：去掉单引号
#!/bin/sh
set -e

REPO_DIR="/app/repo"
TEMP_REPO_DIR="/app/repo_temp"
REPO_URL="$REPO_URL"  # 传入环境变量中的仓库地址

echo "开始拉取最新代码（仓库地址：\$REPO_URL）..."  # 调试用，可保留

# 首次启动：用临时目录克隆
if [ ! -d "\$REPO_DIR/.git" ]; then
    echo "首次启动，用临时目录克隆仓库..."
    rm -rf "\$TEMP_REPO_DIR"
    mkdir -p "\$TEMP_REPO_DIR"
    git clone "\$REPO_URL" "\$TEMP_REPO_DIR" || { echo "克隆仓库失败（地址：\$REPO_URL）"; exit 1; }

    mkdir -p "\$REPO_DIR"
    cp -r "\$TEMP_REPO_DIR"/* "\$REPO_DIR/" 2>/dev/null || true
    cp -r "\$TEMP_REPO_DIR"/.git "\$REPO_DIR/"
    rm -rf "\$TEMP_REPO_DIR"
else
    # 非首次启动：拉取更新
    echo "非首次启动，拉取更新..."
    cd "\$REPO_DIR" || exit 1
    git pull || { echo "拉取代码失败"; exit 1; }
fi

# 安装依赖
cd "\$REPO_DIR" || exit 1
if [ -f "requirements.txt" ]; then
    echo "安装依赖..."
    python -m pip install --no-cache-dir -r requirements.txt || { echo "依赖安装失败"; exit 1; }
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
$PULL_CRON /usr/local/bin/pull_and_update >>  /app/logs/pull.log 2>&1

# 定时执行主程序
$CRON_SCHEDULE /usr/local/bin/python -u $REPO_DIR/src/main.py >> /app/logs/main.log 2>&1
EOF
)

# 写入 crontab
echo "$CRON_JOBS" | crontab -

# 启动 cron 服务
echo "启动定时任务服务..."
# 启动 cronie 服务，保持前台运行
crond -n