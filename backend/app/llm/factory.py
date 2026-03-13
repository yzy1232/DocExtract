"""
LLM 工厂 - 根据配置创建对应的 LLM 适配器
支持多模型路由和降级策略
"""
import logging
from typing import Optional, Dict
from app.llm.base_adapter import BaseLLMAdapter, LLMConfig
from app.llm.openai_adapter import OpenAICompatibleAdapter
from app.config import settings
from app.core.exceptions import LLMException

logger = logging.getLogger(__name__)

# 适配器实例缓存（按 provider:model 缓存）
_adapter_cache: Dict[str, BaseLLMAdapter] = {}


def create_adapter(provider: str, api_key: str, base_url: str) -> BaseLLMAdapter:
    """
    创建 LLM 适配器实例。
    目前所有云服务提供商均使用 OpenAI 兼容协议。
    """
    cache_key = f"{provider}:{base_url}"
    if cache_key not in _adapter_cache:
        _adapter_cache[cache_key] = OpenAICompatibleAdapter(
            api_key=api_key,
            base_url=base_url,
            provider=provider,
        )
    return _adapter_cache[cache_key]


def get_adapter_by_provider(provider: str) -> BaseLLMAdapter:
    """根据提供商名称从系统配置中获取适配器"""
    provider = provider.lower()

    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise LLMException(message="OpenAI API Key 未配置")
        return create_adapter("openai", settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL)

    if provider == "deepseek":
        if not settings.DEEPSEEK_API_KEY:
            raise LLMException(message="DeepSeek API Key 未配置")
        return create_adapter("deepseek", settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_BASE_URL)

    if provider == "ollama":
        return create_adapter("ollama", "ollama", settings.OLLAMA_BASE_URL)

    if provider == "custom":
        # 当使用自定义提供商时，要求至少配置 BASE_URL；若已配置 BASE_URL，则必须同时提供 API Key
        if not settings.CUSTOM_BASE_URL:
            raise LLMException(message="自定义提供商 BASE_URL 未配置")
        if not settings.CUSTOM_API_KEY:
            raise LLMException(message="自定义提供商 API Key 未配置")
        return create_adapter("custom", settings.CUSTOM_API_KEY, settings.CUSTOM_BASE_URL)

    raise LLMException(message=f"不支持的 LLM 提供商: {provider}")


def get_default_adapter() -> BaseLLMAdapter:
    """获取系统默认 LLM 适配器"""
    return get_adapter_by_provider(settings.DEFAULT_LLM_PROVIDER)


def get_default_llm_config(provider: Optional[str] = None, model: Optional[str] = None) -> LLMConfig:
    """获取默认 LLM 配置"""
    provider = provider or settings.DEFAULT_LLM_PROVIDER

    model_defaults = {
        "openai": settings.OPENAI_DEFAULT_MODEL,
        "deepseek": settings.DEEPSEEK_DEFAULT_MODEL,
        "ollama": settings.OLLAMA_DEFAULT_MODEL,
        "custom": settings.CUSTOM_DEFAULT_MODEL,
    }

    return LLMConfig(
        model=model or model_defaults.get(provider, settings.DEFAULT_LLM_MODEL),
        temperature=settings.OPENAI_TEMPERATURE,
        max_tokens=settings.OPENAI_MAX_TOKENS,
        timeout=settings.LLM_REQUEST_TIMEOUT,
    )


def create_adapter_from_db_config(
    api_key: str,
    base_url: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> BaseLLMAdapter:
    """
    使用数据库中存储的凭据直接创建适配器（跳过系统配置）。
    适用于自定义提供商或 DB 中单独配置了 base_url / api_key 的场景。
    如果未提供 provider，会默认为 'custom'。
    """
    prov = provider or "custom"
    return OpenAICompatibleAdapter(
        api_key=api_key or "custom",
        base_url=base_url,
        provider=prov,
        test_model=model,
    )


async def try_providers_in_order(providers: list[str]) -> Optional[BaseLLMAdapter]:
    """降级策略：按顺序尝试可用的提供商"""
    for provider in providers:
        try:
            adapter = get_adapter_by_provider(provider)
            if await adapter.test_connection():
                return adapter
        except (LLMException, Exception) as e:
            logger.warning(f"提供商 {provider} 不可用: {e}")
    return None
