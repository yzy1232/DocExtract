"""
通用 Pydantic 模式定义
"""
from pydantic import BaseModel, Field
from typing import Optional, Any, Generic, TypeVar, List
from datetime import datetime

T = TypeVar("T")


class ResponseBase(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    code: int = 200
    message: str = "success"
    data: Optional[T] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PageInfo(BaseModel):
    """分页信息"""
    page: int = Field(ge=1, description="当前页码")
    page_size: int = Field(ge=1, le=200, description="每页条数")
    total: int = Field(ge=0, description="总条数")
    total_pages: int = Field(ge=0, description="总页数")


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    pagination: PageInfo


class QueryParams(BaseModel):
    """通用查询参数"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    keyword: Optional[str] = Field(default=None, description="搜索关键词")
    order_by: Optional[str] = Field(default="created_at", description="排序字段")
    order_dir: Optional[str] = Field(default="desc", pattern="^(asc|desc)$")


class IDResponse(BaseModel):
    """创建资源后返回ID"""
    id: str


class BatchRequest(BaseModel):
    """批量操作请求"""
    ids: List[str] = Field(min_length=1, max_length=100)


class MessageResponse(BaseModel):
    """简单消息响应"""
    message: str
