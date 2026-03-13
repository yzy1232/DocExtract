FROM python:3.11-slim

# 系统依赖（PyMuPDF 需要）
RUN apt-get update && apt-get install -y \
    libmupdf-dev \
    mupdf-tools \
    gcc \
    g++ \
    curl \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖安装（分层缓存，使用国内镜像加速）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 非 root 用户运行（安全最佳实践）
RUN useradd -r -s /bin/false appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 生产环境使用 gunicorn + uvicorn workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
