"""
Redis 缓存管理模块
"""
import json
import pickle
from typing import Optional, Any, Union
from redis.asyncio import Redis, ConnectionPool
from app.config import settings

# 全局连接池
_pool: Optional[ConnectionPool] = None
_redis_client: Optional[Redis] = None

# 缓存 Key 前缀常量
KEY_USER_SESSION = "session:user:{user_id}"
KEY_TOKEN_BLACKLIST = "blacklist:token:{token_hash}"
KEY_TEMPLATE_CACHE = "cache:template:{template_id}"
KEY_DOCUMENT_CACHE = "cache:document:{document_id}"
KEY_EXTRACTION_PROGRESS = "progress:extraction:{task_id}"
KEY_RATE_LIMIT = "ratelimit:{identifier}:{window}"
KEY_TASK_QUEUE = "queue:extraction"
KEY_DISTRIBUTED_LOCK = "lock:{resource}:{resource_id}"


async def get_redis() -> Redis:
    """获取 Redis 客户端（带连接池）"""
    global _pool, _redis_client
    if _redis_client is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=False,
        )
        _redis_client = Redis(connection_pool=_pool)
    return _redis_client


async def close_redis():
    """关闭 Redis 连接"""
    global _redis_client, _pool
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
    if _pool:
        await _pool.disconnect()
        _pool = None


class CacheManager:
    """缓存管理器"""

    def __init__(self, redis: Redis):
        self.redis = redis

    async def get(self, key: str, as_json: bool = True) -> Any:
        """获取缓存值"""
        value = await self.redis.get(key)
        if value is None:
            return None
        if as_json:
            return json.loads(value)
        return value

    async def set(self, key: str, value: Any, expire: int = 3600, as_json: bool = True) -> bool:
        """设置缓存值"""
        if as_json:
            data = json.dumps(value, ensure_ascii=False, default=str)
        else:
            data = value
        return await self.redis.set(key, data, ex=expire)

    async def delete(self, *keys: str) -> int:
        """删除缓存"""
        if not keys:
            return 0
        return await self.redis.delete(*keys)

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        return bool(await self.redis.exists(key))

    async def expire(self, key: str, seconds: int) -> bool:
        """设置过期时间"""
        return bool(await self.redis.expire(key, seconds))

    async def incr(self, key: str, amount: int = 1) -> int:
        """原子递增"""
        return await self.redis.incrby(key, amount)

    async def get_progress(self, task_id: str) -> Optional[dict]:
        """获取任务进度"""
        key = KEY_EXTRACTION_PROGRESS.format(task_id=task_id)
        return await self.get(key)

    async def set_progress(self, task_id: str, progress: float, message: str = "", ttl: int = 3600):
        """更新任务进度"""
        key = KEY_EXTRACTION_PROGRESS.format(task_id=task_id)
        await self.set(key, {"progress": progress, "message": message}, expire=ttl)

    async def check_rate_limit(self, identifier: str, limit: int, window_seconds: int) -> bool:
        """检查并更新限流计数器，返回 True 表示未超限"""
        import time
        window = int(time.time()) // window_seconds
        key = KEY_RATE_LIMIT.format(identifier=identifier, window=window)
        count = await self.incr(key)
        if count == 1:
            await self.expire(key, window_seconds)
        return count <= limit

    async def acquire_lock(self, resource: str, resource_id: str, ttl: int = 30) -> bool:
        """获取分布式锁"""
        key = KEY_DISTRIBUTED_LOCK.format(resource=resource, resource_id=resource_id)
        return bool(await self.redis.set(key, "1", ex=ttl, nx=True))

    async def release_lock(self, resource: str, resource_id: str):
        """释放分布式锁"""
        key = KEY_DISTRIBUTED_LOCK.format(resource=resource, resource_id=resource_id)
        await self.delete(key)

    async def add_to_blacklist(self, token_hash: str, ttl: int):
        """将 Token 加入黑名单（登出时使用）"""
        key = KEY_TOKEN_BLACKLIST.format(token_hash=token_hash)
        await self.set(key, "1", expire=ttl, as_json=False)

    async def is_blacklisted(self, token_hash: str) -> bool:
        """检查 Token 是否在黑名单中"""
        key = KEY_TOKEN_BLACKLIST.format(token_hash=token_hash)
        return await self.exists(key)


async def get_cache_manager() -> CacheManager:
    """FastAPI 依赖注入 - 获取缓存管理器"""
    redis = await get_redis()
    return CacheManager(redis)
