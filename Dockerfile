# 第一阶段：构建依赖（有 musllinux wheel 时 pip 直接用 wheel，否则用下列工具链编译）
FROM python:3.12-alpine3.21 AS builder

WORKDIR /app

# cryptography / Pillow / PyYAML 等的编译期依赖
RUN apk add --no-cache gcc musl-dev openssl-dev libffi-dev yaml-dev

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/app/deps -r requirements.txt


# 第二阶段：运行镜像
# 说明：代码直接烤进镜像（不再在运行时 git clone/pull），保证"镜像即版本"、可复现、可回滚。
#       升级流程改为：推 v* tag → CI 构建带版本号的镜像 → 目标机拉取新 tag 重启。
FROM python:3.12-alpine3.21

WORKDIR /app

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ca-certificates：HTTPS 请求；tzdata：让 TZ=Asia/Shanghai 真正生效
#（以日期命名的歌单匹配依赖容器本地时区，缺 tzdata 会退回 UTC 造成跨零点错配）
RUN apk add --no-cache ca-certificates tzdata \
    && mkdir -p /app/logs /app/downloads

# 依赖 + 应用代码 + 入口脚本
COPY --from=builder /app/deps /usr/local/lib/python3.12/site-packages/
COPY src/ /app/src/
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
