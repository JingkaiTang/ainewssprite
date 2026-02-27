"""LLM Provider 抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """LLM 服务提供者抽象基类。"""

    @abstractmethod
    def chat(self, prompt: str, system: str = "") -> str:
        """发送单轮对话，返回文本响应。"""
        ...
