# Dockerfile — XiaoPaw v3 主服务镜像
# 基于 docs/08-deployment.md §3.2，适配 uv + pyproject.toml 依赖管理

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

# 编译时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（极速 Python 包管理器）
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /build

# 仅复制依赖文件触发 layer 缓存
COPY pyproject.toml uv.lock ./

# 使用 uv 安装所有依赖到独立目录
RUN uv pip install --system --target=/deps -r pyproject.toml --extra full --extra export \
    && rm -rf /root/.cache

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ARG GIT_SHA=unknown
ARG BUILD_DATE
ARG XIAOPAW_VERSION=v3.0.0

# 运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        curl \
        tini \
        # WeasyPrint 运行时依赖
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        libcairo2 \
        libglib2.0-0 \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# OCI 标签
LABEL org.opencontainers.image.title="xiaopaw" \
      org.opencontainers.image.version="${XIAOPAW_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV GIT_SHA=${GIT_SHA} \
    XIAOPAW_VERSION=${XIAOPAW_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/deps \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 源代码 + 前端构建产物（frontend/build 由宿主机 npm run build 产出）
COPY --chown=65534:65534 xiaopaw/ ./xiaopaw/
COPY --chown=65534:65534 shared_hooks/ ./shared_hooks/
COPY --chown=65534:65534 workspace-init/ ./workspace-init/
COPY --chown=65534:65534 frontend/build/ ./frontend/build/

# 依赖目录（从 builder）
COPY --from=builder /deps /deps

# 数据目录挂载点
RUN mkdir -p /app/data && chown -R 65534:65534 /app /deps

# 非 root 用户
USER 65534:65534

VOLUME ["/app/data"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8080/ || exit 1

# tini 作为 PID 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "xiaopaw.main"]
