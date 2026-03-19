"""
OpenAI 兼容适配器 - 支持 OpenAI 及所有兼容 OpenAI API 的提供商
(DeepSeek、Moonshot、智谱、Ollama 等均可通过此适配器对接)
"""
import asyncio
import json
import logging
from typing import List, AsyncGenerator, Optional
from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError
from app.llm.base_adapter import BaseLLMAdapter, LLMMessage, LLMResponse, LLMConfig
from app.core.exceptions import LLMException


LLM_ADAPTER_LOG_MAX_CHARS = 4000
logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """OpenAI 兼容协议适配器"""

    def __init__(self, api_key: str, base_url: str, provider: str = "openai", test_model: Optional[str] = None):
        self._provider = provider
        self._test_model = test_model
        normalized_base_url = self._normalize_base_url(base_url)
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=normalized_base_url,
        )

    @property
    def provider_name(self) -> str:
        return self._provider

    def _truncate_for_log(self, value, max_chars: int = LLM_ADAPTER_LOG_MAX_CHARS) -> str:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False)
            except Exception:
                text = str(value)

        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}... [truncated {len(text) - max_chars} chars]"

    async def chat(self, messages: List[LLMMessage], config: LLMConfig) -> LLMResponse:
        """发送聊天请求（带重试）"""
        last_exception = None
        request_messages = self._build_messages_dicts(messages)
        logger.info(
            "LLM请求: provider=%s model=%s temperature=%s max_tokens=%s messages=%s",
            self._provider,
            config.model,
            config.temperature,
            config.max_tokens,
            self._truncate_for_log(request_messages),
        )

        for attempt in range(3):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=config.model,
                        messages=request_messages,
                        temperature=config.temperature,
                        max_tokens=config.max_tokens,
                        top_p=config.top_p,
                        **config.extra_params,
                    ),
                    timeout=config.timeout,
                )
                choice = response.choices[0]
                usage = response.usage

                logger.info(
                    "LLM响应: provider=%s model=%s finish_reason=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s content=%s",
                    self._provider,
                    response.model,
                    choice.finish_reason or "stop",
                    usage.prompt_tokens if usage else 0,
                    usage.completion_tokens if usage else 0,
                    usage.total_tokens if usage else 0,
                    self._truncate_for_log(choice.message.content or ""),
                )

                return LLMResponse(
                    content=choice.message.content or "",
                    model=response.model,
                    provider=self._provider,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                    finish_reason=choice.finish_reason or "stop",
                    raw_response=response.model_dump(),
                )

            except RateLimitError as e:
                last_exception = e
                wait_time = 2 ** attempt
                logger.warning(
                    "LLM限流，准备重试: provider=%s model=%s attempt=%s wait_seconds=%s error=%s",
                    self._provider,
                    config.model,
                    attempt + 1,
                    wait_time,
                    str(e),
                )
                await asyncio.sleep(wait_time)

            except (APIConnectionError, asyncio.TimeoutError) as e:
                last_exception = e
                logger.warning(
                    "LLM连接或超时错误，准备重试: provider=%s model=%s attempt=%s error=%s",
                    self._provider,
                    config.model,
                    attempt + 1,
                    str(e),
                )
                await asyncio.sleep(1)

            except APIError as e:
                logger.exception(
                    "LLM API错误: provider=%s model=%s error=%s",
                    self._provider,
                    config.model,
                    e.message,
                )
                raise LLMException(
                    message=f"{self._provider} API 错误: {e.message}",
                    detail=str(e),
                )

        raise LLMException(
            message=f"{self._provider} 请求失败（已重试3次）",
            detail=str(last_exception),
        )

    async def chat_stream(
        self, messages: List[LLMMessage], config: LLMConfig
    ) -> AsyncGenerator[str, None]:
        """流式响应"""
        try:
            stream = await self._client.chat.completions.create(
                model=config.model.strip(),
                messages=self._build_messages_dicts(messages),
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except APIError as e:
            raise LLMException(message=f"流式请求失败: {e.message}")

    async def test_connection(self) -> bool:
        """测试连接"""
        model = self._get_test_model()
        payload_variants = [
            {"max_tokens": 5},
            {"max_completion_tokens": 5},
            {},
        ]
        last_error: Optional[Exception] = None

        try:
            for extra_kwargs in payload_variants:
                try:
                    await asyncio.wait_for(
                        self._client.chat.completions.create(
                            model=model,
                            messages=[{"role": "user", "content": "hi"}],
                            **extra_kwargs,
                        ),
                        timeout=15,
                    )
                    return True
                except TypeError as e:
                    # 部分 SDK 版本可能不支持 max_completion_tokens 等参数，继续尝试兼容分支。
                    last_error = e
                    continue
                except APIError as e:
                    # 模型或网关可能拒绝某些参数形式，继续尝试下一种请求体。
                    last_error = e
                    continue
                except Exception as e:
                    last_error = e
                    continue
            if last_error:
                raise LLMException(message=f"{self._provider} 连接测试失败", detail=str(last_error))
            return False
        except LLMException:
            raise
        except Exception as e:
            raise LLMException(message=f"{self._provider} 连接测试失败", detail=str(e))

    def _normalize_base_url(self, base_url: str) -> str:
        """统一 base_url，避免把完整 endpoint 当作 base URL 导致 400/404。"""
        if not base_url:
            return base_url

        normalized = base_url.strip().rstrip("/")
        for suffix in ("/chat/completions", "/v1/chat/completions"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        return normalized

    def _get_test_model(self) -> str:
        """获取测试时使用的模型"""
        if self._test_model:
            return self._test_model
        raise LLMException(message=f"{self._provider} 连接测试失败", detail="未指定测试模型，无法进行连接测试")
