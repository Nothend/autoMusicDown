FROM python:3.12.0-alpine3.19

# 设置工作目录
WORKDIR /app

# 设置时区
ENV TZ=Asia/Shanghai

# 安装所有必需的系统依赖
RUN apk add --no-cache \
    gcc \
    musl-dev \
    openssl-dev \
    libffi-dev \
    libyaml-dev \
    libmagic-dev \
    && rm -rf /var/cache/apk/*  # 清理缓存，减小镜像体积
# 创建日志目录和默认下载目录
RUN mkdir -p /app/logs /app/downloads \
    && chmod 777 /app/logs /app/downloads
    
# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 生产环境优化：卸载编译工具（节省空间）
RUN apk del gcc musl-dev \
    && rm -rf /var/cache/apk/*

# 复制项目文件
COPY . .

# 运行程序
CMD ["python", "-u", "src/main.py"]