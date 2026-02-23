"""
LangChain adapter wrapping Zero's UnifiedLLMClient.

Provides a LangChain-compatible ChatModel interface that delegates to
the multi-provider unified client, preserving circuit breaker, connection
pooling, retry logic, fallback chains, and cost tracking.

Usage in LangGraph nodes that need tool-calling:
    from app.infrastructure.langchain_adapter import get_zero_chat_model
    llm = get_zero_chat_model(task_type="chat")
    result = await llm.ainvoke([HumanMessage(content="hello")])
"""

from typing import Any, List, Optional
from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration

import structlog

logger = structlog.get_logger(__name__)


class ZeroChatModel(BaseChatModel):
    """LangChain ChatModel backed by Zero's UnifiedLLMClient.

    Routes through the multi-provider system automatically.
    model_name can be 'provider/model' format (e.g., 'gemini/gemini-3.1-pro-preview').
    """

    task_type: str = "chat"
    temperature: float = 0.3
    num_predict: int = 2048
    model_name: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "zero-unified"

    def _generate(self, messages: List[BaseMessage], **kwargs: Any) -> ChatResult:
        raise NotImplementedError("Use async ainvoke/agenerate instead")

    async def _agenerate(self, messages: List[BaseMessage], **kwargs: Any) -> ChatResult:
        from app.infrastructure.unified_llm_client import get_unified_llm_client

        client = get_unified_llm_client()

        # Convert LangChain messages to standard dict format
        converted = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                converted.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                converted.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                converted.append({"role": "assistant", "content": msg.content})

        result = await client.chat(
            messages=converted,
            model=self.model_name,
            task_type=self.task_type,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("num_predict", self.num_predict),
        )

        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=result or ""))]
        )


@lru_cache()
def get_zero_chat_model(task_type: str = "chat", temperature: float = 0.3) -> ZeroChatModel:
    """Get a cached ZeroChatModel instance for the given task type."""
    return ZeroChatModel(task_type=task_type, temperature=temperature)
