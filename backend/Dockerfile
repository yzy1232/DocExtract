FROM python:3.11-slim

# 支持构建时传入 apt 镜像域名，默认使用清华源
ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn

# 支持构建时传入 pip 镜像，默认使用清华源并回退官方源
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_EXTRA_INDEX_URL=https://pypi.org/simple

# 避免 tzdata 安装交互提示，并设置默认时区为上海（可按需修改）
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 系统依赖（PyMuPDF 需要）。包含 tzdata 以提供 /usr/share/zoneinfo
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
            sed -i "s|http://deb.debian.org|https://${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
        fi \
        && if [ -f /etc/apt/sources.list ]; then \
            sed -i "s|http://deb.debian.org/debian|https://${APT_MIRROR}/debian|g; s|http://deb.debian.org/debian-security|https://${APT_MIRROR}/debian-security|g; s|http://security.debian.org/debian-security|https://${APT_MIRROR}/debian-security|g" /etc/apt/sources.list; \
        fi \
        && apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    libmupdf-dev \
    mupdf-tools \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    gcc \
    g++ \
    curl \
    ca-certificates \
    && ln -sf /usr/share/zoneinfo/$TZ /etc/localtime \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖安装（分层缓存，使用国内镜像加速）
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir \
    -i ${PIP_INDEX_URL} \
    --extra-index-url ${PIP_EXTRA_INDEX_URL} \
    -r requirements.txt

# 复制应用代码
COPY . .

# 非 root 用户运行（安全最佳实践）
RUN useradd -r -s /bin/false appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 生产环境使用 gunicorn + uvicorn workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
