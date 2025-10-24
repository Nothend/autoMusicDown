# 第一阶段：构建阶段（设置REPO_URL默认值）
FROM python:3.12-alpine3.21 AS builder

WORKDIR /app

# 安装构建依赖
RUN apk update && apk add --no-cache \
    gcc \
    musl-dev \
    openssl-dev \
    libffi-dev \
    yaml-dev \
    file-dev \
    git \
    && rm -rf /var/cache/apk/*

# 设置REPO_URL默认值（如果构建时不传入，自动使用此地址）
ARG REPO_URL="https://github.com/Nothend/autoMusicDown.git"

# 克隆远程仓库（使用默认或传入的REPO_URL）
RUN echo "从 $REPO_URL 克隆仓库..." && \
    git clone "$REPO_URL" . || { \
        echo "错误：克隆仓库失败，请检查REPO_URL是否正确或网络是否通畅"; \
        exit 1; \
    }

# 确认 requirements.txt 存在
RUN if [ ! -f "requirements.txt" ]; then \
        echo "错误：远程仓库根目录中未找到 requirements.txt，请检查仓库结构"; \
        exit 1; \
    fi

# 安装依赖到 /app/deps
RUN echo "安装依赖到 /app/deps..." && \
    pip install --no-cache-dir --target=/app/deps -r requirements.txt


# 第二阶段：运行阶段
FROM python:3.12-alpine3.21

WORKDIR /app

# 设置时区
ENV TZ=Asia/Shanghai

# 安装运行必需工具
RUN apk update && apk add --no-cache \
    dcron \
    git \
    ca-certificates \
    && rm -rf /var/cache/apk/*

# 创建必要目录
RUN mkdir -p /app/logs /app/downloads /app/repo /var/log/cron \
    && chmod 777 /app/logs /app/downloads /app/repo /var/log/cron

# 从构建阶段复制依赖
COPY --from=builder /app/deps /usr/local/lib/python3.12/site-packages/

# 复制入口脚本
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 入口点
ENTRYPOINT ["./entrypoint.sh"]