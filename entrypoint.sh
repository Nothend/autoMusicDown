#!/bin/sh
set -e  # 遇到错误立即退出
# 定义时间格式化函数（简化重复调用）
log_time() {
  date +"%Y-%m-%d %H:%M:%S %Z"  # %Z 显示当前时区（如 CST）
}
# 定义最终代码目录和临时克隆目录
REPO_DIR="/app/repo"
TEMP_REPO_DIR="/app/repo_temp"  # 临时目录（无挂载，确保空）

# 检查必要环境变量
if [ -z "$REPO_URL" ]; then
    echo "[$(log_time)] 错误：未设置 REPO_URL 环境变量（仓库地址）"
    exit 1
fi
if [ -z "$CRON_SCHEDULE" ]; then
    echo "[$(log_time)] 错误：未设置 CRON_SCHEDULE 环境变量（执行任务的cron表达式）"
    exit 1
fi

# 将拉取逻辑写成独立脚本（用 EOF 而非 'EOF'，允许变量展开）
cat > /usr/local/bin/pull_and_update << EOF  # 关键：去掉单引号
#!/bin/sh
set -e
# 子脚本中同样定义时间格式化函数
log_time() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}
REPO_DIR="/app/repo"
TEMP_REPO_DIR="/app/repo_temp"
REPO_URL="$REPO_URL"  # 传入环境变量中的仓库地址

echo "[\$(log_time)] 开始拉取最新代码（仓库地址：\$REPO_URL）..."  # 调试用

# 首次启动：用临时目录克隆
if [ ! -d "\$REPO_DIR/.git" ]; then
    echo "[\$(log_time)] 首次启动，用临时目录克隆仓库..."
    rm -rf "\$TEMP_REPO_DIR"
    mkdir -p "\$TEMP_REPO_DIR"
    git clone "\$REPO_URL" "\$TEMP_REPO_DIR" || { echo "[\$(log_time)] 克隆仓库失败（地址：\$REPO_URL）"; exit 1; }

    mkdir -p "\$REPO_DIR"
    cp -r "\$TEMP_REPO_DIR"/* "\$REPO_DIR/" 2>/dev/null || true
    cp -r "\$TEMP_REPO_DIR"/.git "\$REPO_DIR/"
    rm -rf "\$TEMP_REPO_DIR"
else
    # 非首次启动：拉取更新
    echo "非首次启动，拉取更新..."
    cd "\$REPO_DIR" || exit 1
    git pull ||  { echo "[\$(log_time)] 拉取代码失败"; exit 1; }
fi

# 安装依赖
cd "\$REPO_DIR" || exit 1
if [ -f "requirements.txt" ]; then
    echo "[\$(log_time)] 安装依赖..."
    python -m pip install --no-cache-dir -r requirements.txt || { echo "依赖安装失败"; exit 1; }
fi

echo "[\$(log_time)] 代码拉取和依赖更新完成"
EOF

# 给脚本添加执行权限
chmod +x /usr/local/bin/pull_and_update

# 初始拉取代码（容器启动时执行一次）
pull_and_update

# 配置定时任务（修正语法：去掉多余引号，调用独立脚本）
PULL_CRON=${PULL_CRON:-"0 18 * * *"}  # 默认定时拉取：每天18点
CRON_SCHEDULE=${CRON_SCHEDULE:-"0 20-23,0 * * *"}  # 默认定时运行：每天20-23点及0点，每小时一次
echo "[\$(log_time)] 配置代码拉取定时任务：$PULL_CRON"
echo "[\$(log_time)] 配置程序执行定时任务：$CRON_SCHEDULE"


# 生成 crontab 配置（注意：时间表达式和命令之间无引号，调用独立脚本）
CRON_JOBS=$(cat <<EOF
# 定时拉取代码（调用独立脚本，而非函数）
$PULL_CRON /usr/local/bin/pull_and_update 2>&1 

# 定时执行主程序
$CRON_SCHEDULE /usr/local/bin/python -u $REPO_DIR/src/main.py 2>&1
EOF
)

# 写入 crontab 并增加错误处理
if ! echo "$CRON_JOBS" | crontab -; then
    # 输出错误日志（>&2 表示重定向到标准错误流，确保被容器日志捕获）
    echo "[\$(log_time)] 错误：写入crontab配置失败！" >&2
    echo "[\$(log_time)] 失败的crontab配置内容：" >&2
    echo "$CRON_JOBS" >&2  # 输出具体配置内容，方便排查格式问题
    echo "[\$(log_time)] 请检查cron表达式格式或系统权限" >&2
    exit 1  # 失败时退出脚本，避免容器启动后定时任务无效
fi

# 启动 cron 服务
echo "[\$(log_time)] 启动定时任务服务..."
exec crond -f -l 2