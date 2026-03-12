"""
LLM 适配器基类 - 定义统一接口
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, AsyncGenerator


@dataclass
class LLMMessage:
    role: str  # system / user / assistant
    content: str


@dataclass
class LLMResponse:
    """LLM 统一响应格式"""
    content: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class LLMConfig:
    """LLM 调用配置"""
    model: str
    temperature: float = 0.1
    max_tokens: int = 4096
    top_p: float = 1.0
    timeout: int = 120
    extra_params: Dict[str, Any] = field(default_factory=dict)


class BaseLLMAdapter(ABC):
    """LLM 适配器抽象基类"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """提供商名称"""
        ...

    @abstractmethod
    async def chat(
        self,
        messages: List[LLMMessage],
        config: LLMConfig,
    ) -> LLMResponse:
        """发送聊天请求，获取完整响应"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[LLMMessage],
        config: LLMConfig,
    ) -> AsyncGenerator[str, None]:
        """流式聊天请求"""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """测试连接是否可用"""
        ...

    def _build_messages_dicts(self, messages: List[LLMMessage]) -> List[dict]:
        """将 LLMMessage 转换为字典格式"""
        return [{"role": m.role, "content": m.content} for m in messages]
