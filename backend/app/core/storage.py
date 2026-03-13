"""
文件对象存储模块 - 封装 MinIO/S3 操作
"""
import io
import hashlib
from typing import Optional, BinaryIO
from urllib.parse import quote
from minio import Minio
from minio.error import S3Error
from app.config import settings


def _get_minio_client() -> Minio:
    """创建 MinIO 客户端"""
    return Minio(
        endpoint=settings.STORAGE_ENDPOINT,
        access_key=settings.STORAGE_ACCESS_KEY,
        secret_key=settings.STORAGE_SECRET_KEY,
        secure=settings.STORAGE_SECURE,
    )


def ensure_buckets():
    """确保所需存储桶存在"""
    client = _get_minio_client()
    for bucket in [
        settings.STORAGE_BUCKET_DOCUMENTS,
        settings.STORAGE_BUCKET_RESULTS,
        settings.STORAGE_BUCKET_TEMP,
    ]:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)


class StorageManager:
    """对象存储管理器"""

    def __init__(self):
        self._client = _get_minio_client()

    def upload_file(
        self,
        bucket: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict] = None,
    ) -> str:
        """上传文件到对象存储，返回对象名称（storage_path）"""
        # MinIO 用户元数据仅支持 US-ASCII；对非 ASCII 值做百分号编码。
        safe_metadata = self._normalize_metadata(metadata)
        self._client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=data,
            length=length,
            content_type=content_type,
            metadata=safe_metadata,
        )
        return object_name

    @staticmethod
    def _normalize_metadata(metadata: Optional[dict]) -> Optional[dict]:
        if not metadata:
            return metadata

        def to_ascii(value) -> str:
            text = str(value)
            try:
                text.encode("ascii")
                return text
            except UnicodeEncodeError:
                return quote(text, safe="")

        normalized = {}
        for key, value in metadata.items():
            if isinstance(value, (list, tuple, set)):
                normalized[key] = [to_ascii(v) for v in value]
            else:
                normalized[key] = to_ascii(value)
        return normalized

    def upload_bytes(
        self,
        bucket: str,
        object_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """上传字节数据"""
        data = io.BytesIO(content)
        return self.upload_file(bucket, object_name, data, len(content), content_type)

    def download_file(self, bucket: str, object_name: str) -> bytes:
        """下载文件内容"""
        response = self._client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires_seconds: int = 3600,
    ) -> str:
        """生成预签名下载 URL"""
        from datetime import timedelta
        return self._client.presigned_get_object(
            bucket, object_name, expires=timedelta(seconds=expires_seconds)
        )

    def get_upload_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expires_seconds: int = 3600,
    ) -> str:
        """生成预签名上传 URL（用于前端直传）"""
        from datetime import timedelta
        return self._client.presigned_put_object(
            bucket, object_name, expires=timedelta(seconds=expires_seconds)
        )

    def delete_file(self, bucket: str, object_name: str):
        """删除文件"""
        self._client.remove_object(bucket, object_name)

    def file_exists(self, bucket: str, object_name: str) -> bool:
        """检查文件是否存在"""
        try:
            self._client.stat_object(bucket, object_name)
            return True
        except S3Error:
            return False

    def get_file_metadata(self, bucket: str, object_name: str) -> dict:
        """获取文件元数据"""
        try:
            stat = self._client.stat_object(bucket, object_name)
            return {
                "size": stat.size,
                "etag": stat.etag,
                "last_modified": stat.last_modified,
                "content_type": stat.content_type,
            }
        except S3Error:
            return {}

    @staticmethod
    def calculate_sha256(data: bytes) -> str:
        """计算文件 SHA256 哈希"""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def build_document_key(document_id: str, filename: str) -> str:
        """构建文档存储路径"""
        import os
        ext = os.path.splitext(filename)[1].lower()
        return f"documents/{document_id}/original{ext}"

    @staticmethod
    def build_page_image_key(document_id: str, page_number: int) -> str:
        """构建页面图像存储路径"""
        return f"documents/{document_id}/pages/page_{page_number:04d}.jpg"

    @staticmethod
    def build_result_key(task_id: str, export_format: str) -> str:
        """构建导出结果存储路径"""
        return f"results/{task_id}/export.{export_format}"


# 全局单例
storage = StorageManager()
