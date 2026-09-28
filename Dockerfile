
# ============================================================
# PDFFast Service
#
# 当前镜像负责：
#
# 1. PDFFast Core
# 2. FastAPI Service
# 3. 主 Provider Runtime
# 4. MinerU Runtime
# 5. Marker Runtime
# 6. Docling Runtime
#
# 模型 cache 暂时不烘焙进镜像。
# 下一阶段通过 volume 管理。
# ============================================================

FROM python:3.12-slim-bookworm


# ============================================================
# 基础环境
# ============================================================

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PDFFAST_PROJECT_ROOT=/app \
    PDFFAST_OUTPUT_ROOT=/data/outputs


WORKDIR /app


# ============================================================
# 系统运行依赖
#
# build-essential:
#   某些 Python 包无 wheel 时需要编译
#
# libgl / glib / gomp:
#   OCR / OpenCV / Torch 常见运行依赖
#
# poppler:
#   PDF Provider 常用
#
# fonts-noto-cjk:
#   中文文档字体支持
# ============================================================

RUN apt-get update \
    && apt-get install -y \
        --no-install-recommends \
        build-essential \
        git \
        curl \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libmagic1 \
        poppler-utils \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*


# ============================================================
# uv
#
# 这里不依赖宿主机 uv。
# 新电脑只需要 Docker。
# ============================================================

RUN pip install \
    --no-cache-dir \
    "uv>=0.11,<0.12"


# ============================================================
# 先复制依赖声明。
#
# 这样业务代码变化时可以复用 Docker layer cache，
# 不必每次重新安装几 GB 的 Provider 环境。
# ============================================================

COPY pyproject.toml uv.lock ./

COPY runtimes/mineru/pyproject.toml \
     runtimes/mineru/uv.lock \
     ./runtimes/mineru/

COPY runtimes/marker/pyproject.toml \
     runtimes/marker/uv.lock \
     ./runtimes/marker/

COPY runtimes/docling/pyproject.toml \
     runtimes/docling/uv.lock \
     ./runtimes/docling/


# ============================================================
# 主 Runtime
#
# 生成：
#
# /app/.venv
#
# 包含：
# PDFFast Core dependencies
# RapidOCR
# PaddleOCR
# FastAPI Service
# ============================================================

RUN uv sync \
    --frozen \
    --no-install-project \
    --extra service \
    --extra runtime-main


# ============================================================
# MinerU Runtime
#
# 生成：
#
# /app/runtimes/mineru/.venv
# ============================================================

RUN uv sync \
    --project runtimes/mineru \
    --frozen


# ============================================================
# Marker Runtime
# ============================================================

RUN uv sync \
    --project runtimes/marker \
    --frozen


# ============================================================
# Docling Runtime
# ============================================================

RUN uv sync \
    --project runtimes/docling \
    --frozen


# ============================================================
# 最后复制 PDFFast 源码。
#
# 这样修改源码不会破坏前面的依赖缓存层。
# ============================================================

COPY pdffast ./pdffast
COPY configs ./configs
COPY scripts ./scripts


# ============================================================
# 把当前 PDFFast 项目安装进主 Runtime。
#
# --no-deps：
# 依赖已经由 uv.lock 安装完成。
# ============================================================

RUN uv pip install \
    --python .venv/bin/python \
    --no-deps \
    .


# ============================================================
# 输出目录
# ============================================================

RUN mkdir -p \
    /data/outputs


EXPOSE 8010


# ============================================================
# 健康检查
#
# 当前这里只检查 HTTP Service。
# Provider runtime readiness 下一阶段单独检查。
# ============================================================

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=10s \
    --retries=3 \
    CMD curl -f \
        http://127.0.0.1:8010/health \
        || exit 1


# ============================================================
# Service
# ============================================================

CMD [".venv/bin/python", "-m", "uvicorn", "pdffast.service.app:app", "--host", "0.0.0.0", "--port", "8010"]