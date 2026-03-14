"""
系统配置模块 - 使用 pydantic-settings 管理所有配置项
"""
from pydantic_settings import BaseSettings
from typing import Optional, List
import secrets


class Settings(BaseSettings):
    # ========================
    # 应用基础配置
    # ========================
    APP_NAME: str = "文档理解与模板提取系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # CORS 配置
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:80",
        "http://127.0.0.1:3000",
    ]

    # ========================
    # 数据库配置 (MySQL)
    # ========================
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "docextract"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    # ========================
    # Redis 配置
    # ========================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 100

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ========================
    # JWT 认证配置
    # ========================
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24       # 24小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7               # 7天

    # ========================
    # 文件存储配置 (MinIO/S3)
    # ========================
    STORAGE_ENDPOINT: str = "localhost:9000"
    STORAGE_ACCESS_KEY: str = "minioadmin"
    STORAGE_SECRET_KEY: str = "minioadmin"
    STORAGE_BUCKET_DOCUMENTS: str = "documents"
    STORAGE_BUCKET_RESULTS: str = "results"
    STORAGE_BUCKET_TEMP: str = "temp"
    STORAGE_SECURE: bool = False
    # 对外可访问的对象存储地址（用于生成浏览器可访问的预签名 URL）
    # 示例: "http://localhost:9000" 或 "https://storage.example.com"
    STORAGE_PUBLIC_ENDPOINT: Optional[str] = None

    # ========================
    # LLM 提供商配置
    # ========================
    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_DEFAULT_MODEL: str = "gpt-4o"
    OPENAI_MAX_TOKENS: int = 4096
    OPENAI_TEMPERATURE: float = 0.1

    # DeepSeek
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_DEFAULT_MODEL: str = "deepseek-chat"

    # 文心一言
    WENXIN_API_KEY: Optional[str] = None
    WENXIN_SECRET_KEY: Optional[str] = None
    WENXIN_DEFAULT_MODEL: str = "ernie-bot-4"

    # Ollama 本地模型
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_DEFAULT_MODEL: str = "llama3"

    # 自定义提供商（任意 OpenAI 兼容端点）
    CUSTOM_API_KEY: Optional[str] = None
    CUSTOM_BASE_URL: str = "http://localhost:8080/v1"
    CUSTOM_DEFAULT_MODEL: str = "custom-model"

    # 默认 LLM 提供商（代码层面默认改为 custom）
    DEFAULT_LLM_PROVIDER: str = "custom"
    DEFAULT_LLM_MODEL: str = "custom-model"
    LLM_REQUEST_TIMEOUT: int = 120
    LLM_MAX_RETRIES: int = 3
    EXTRACTION_CHUNK_SIZE: int = 7000
    EXTRACTION_CHUNK_OVERLAP: int = 800
    EXTRACTION_CROSS_VALIDATE_ROUNDS: int = 2
    EXTRACTION_MIN_AGREEMENT: int = 2

    # ========================
    # Celery 任务队列配置
    # ========================
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: List[str] = ["json"]
    CELERY_TIMEZONE: str = "Asia/Shanghai"
    CELERY_MAX_WORKERS: int = 4

    # ========================
    # 限流配置
    # ========================
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000
    RATE_LIMIT_UPLOAD_PER_HOUR: int = 100

    # ========================
    # 文件上传配置
    # ========================
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    MAX_BATCH_SIZE: int = 50                  # 单次批量上传最大文件数
    ALLOWED_MIME_TYPES: List[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
    ]

    # ========================
    # OCR 配置
    # ========================
    OCR_ENGINE: str = "tesseract"   # tesseract / paddleocr / easyocr
    OCR_LANGUAGES: List[str] = ["chi_sim", "eng"]

    # ========================
    # 日志配置
    # ========================
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"         # json / text
    LOG_FILE: Optional[str] = None

    # ========================
    # 默认管理员用配置（首次启动自动创建）
    # ========================
    AUTO_CREATE_ADMIN: bool = True
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
