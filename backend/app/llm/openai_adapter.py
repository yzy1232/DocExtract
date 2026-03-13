"""
OpenAI 兼容适配器 - 支持 OpenAI 及所有兼容 OpenAI API 的提供商
(DeepSeek、Moonshot、智谱、Ollama 等均可通过此适配器对接)
"""
import asyncio
from typing import List, AsyncGenerator, Optional
from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError
from app.llm.base_adapter import BaseLLMAdapter, LLMMessage, LLMResponse, LLMConfig
from app.core.exceptions import LLMException


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """OpenAI 兼容协议适配器"""

    def __init__(self, api_key: str, base_url: str, provider: str = "openai", test_model: Optional[str] = None):
        self._provider = provider
        self._test_model = test_model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    @property
    def provider_name(self) -> str:
        return self._provider

    async def chat(self, messages: List[LLMMessage], config: LLMConfig) -> LLMResponse:
        """发送聊天请求（带重试）"""
        last_exception = None
        for attempt in range(3):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=config.model,
                        messages=self._build_messages_dicts(messages),
                        temperature=config.temperature,
                        max_tokens=config.max_tokens,
                        top_p=config.top_p,
                        **config.extra_params,
                    ),
                    timeout=config.timeout,
                )
                choice = response.choices[0]
                usage = response.usage

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
                await asyncio.sleep(wait_time)

            except (APIConnectionError, asyncio.TimeoutError) as e:
                last_exception = e
                await asyncio.sleep(1)

            except APIError as e:
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
                model=config.model,
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
        try:
            await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._get_test_model(),
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=5,
                ),
                timeout=15,
            )
            return True
        except Exception:
            return False

    def _get_test_model(self) -> str:
        """获取测试时使用的模型"""
        if self._test_model:
            return self._test_model

        test_models = {
            "openai": "gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "default": "gpt-3.5-turbo",
        }
        return test_models.get(self._provider, test_models["default"])
