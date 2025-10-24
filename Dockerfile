FROM python:3.12-alpine3.21

WORKDIR /app

# 设置时区
ENV TZ=Asia/Shanghai

# 安装系统依赖（新增 git 和 cron）
RUN apk update && apk add --no-cache \
    gcc \
    musl-dev \
    openssl-dev \
    libffi-dev \
    yaml-dev \
    file-dev \
    ca-certificates \
    git \          
    cron \       
    && rm -rf /var/cache/apk/*
# 用于克隆代码库
 # 用于定时任务
# 创建必要目录（含 cron 日志目录）
RUN mkdir -p /app/logs /app/downloads /var/log/cron \
    && chmod 777 /app/logs /app/downloads /var/log/cron

# 复制入口脚本
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 入口点设置为脚本
ENTRYPOINT ["./entrypoint.sh"]