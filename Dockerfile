FROM node:20-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

ARG DEBIAN_MIRROR_HTTP=http://mirrors.cloud.tencent.com/debian
ARG DEBIAN_SECURITY_MIRROR_HTTP=http://mirrors.cloud.tencent.com/debian-security

ARG DEBIAN_MIRROR_HTTPS=https://mirrors.cloud.tencent.com/debian
ARG DEBIAN_SECURITY_MIRROR_HTTPS=https://mirrors.cloud.tencent.com/debian-security

ARG NPM_REGISTRY=https://mirrors.cloud.tencent.com/npm/
ARG WEREAD_CLI_VERSION=0.18.0

# 第一阶段：
# node:20-bookworm-slim 默认没有 CA 证书，
# 先通过 HTTP 软件源安装 ca-certificates。
RUN set -eux; \
    rm -f /etc/apt/sources.list; \
    rm -f /etc/apt/sources.list.d/debian.sources; \
    printf '%s\n' \
        'Types: deb' \
        "URIs: ${DEBIAN_MIRROR_HTTP}" \
        'Suites: bookworm bookworm-updates' \
        'Components: main contrib non-free non-free-firmware' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        '' \
        'Types: deb' \
        "URIs: ${DEBIAN_SECURITY_MIRROR_HTTP}" \
        'Suites: bookworm-security' \
        'Components: main contrib non-free non-free-firmware' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        > /etc/apt/sources.list.d/debian.sources; \
    cat /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates; \
    update-ca-certificates; \
    rm -rf /var/lib/apt/lists/*

# 第二阶段：
# CA 证书安装完成后，改用 HTTPS 腾讯源安装其余依赖。
RUN set -eux; \
    printf '%s\n' \
        'Types: deb' \
        "URIs: ${DEBIAN_MIRROR_HTTPS}" \
        'Suites: bookworm bookworm-updates' \
        'Components: main contrib non-free non-free-firmware' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        '' \
        'Types: deb' \
        "URIs: ${DEBIAN_SECURITY_MIRROR_HTTPS}" \
        'Suites: bookworm-security' \
        'Components: main contrib non-free non-free-firmware' \
        'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
        > /etc/apt/sources.list.d/debian.sources; \
    cat /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        xvfb \
        xauth \
        x11-utils \
        python3 \
        python3-flask \
        curl \
        dumb-init \
        procps \
        psmisc \
        util-linux \
        fonts-liberation \
        fonts-noto-cjk; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# 兼容部分程序默认寻找的 Chrome 可执行文件名。
RUN set -eux; \
    ln -sf /usr/bin/chromium /usr/bin/google-chrome; \
    ln -sf /usr/bin/chromium /usr/bin/google-chrome-stable

# 使用腾讯云 npm 镜像安装微信读书 CLI。
RUN set -eux; \
    npm install -g \
        --registry="${NPM_REGISTRY}" \
        "weread-selenium-cli@${WEREAD_CLI_VERSION}"; \
    npm cache clean --force

# 删除 Node 官方镜像中的默认 node 用户，
# 创建 UID 1000 的普通运行用户。
RUN set -eux; \
    userdel -r node 2>/dev/null || true; \
    useradd -m -u 1000 -s /bin/bash user; \
    mkdir -p /data/.weread; \
    chown -R user:user /data /home/user

WORKDIR /app

COPY --chown=user:user app.py entrypoint.sh start_reading.sh feishu_notify.py ./
COPY --chown=user:user notification_settings.py notification_delivery.py dashboard_helpers.py ./
COPY --chown=user:user templates ./templates
COPY --chown=user:user static ./static

RUN set -eux; \
    chmod +x /app/entrypoint.sh /app/start_reading.sh; \
    chown -R user:user /app

ENV HOME=/home/user \
    DISPLAY=:99 \
    PORT=7860 \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver \
    WEREAD_BROWSER=chrome \
    WEREAD_DATA_DIR=/data/.weread \
    WEREAD_DURATION=68 \
    WEREAD_SPEED=slow \
    WEREAD_SELECTION=2 \
    WEREAD_SCREENSHOT=true \
    WEREAD_AGREE_TERMS=true \
    READING_INTERVAL_HOURS=12 \
    SELF_PING_MINUTES=5

USER user

EXPOSE 7860

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7860/healthz >/dev/null || exit 1

ENTRYPOINT ["dumb-init", "--", "/app/entrypoint.sh"]
