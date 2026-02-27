"""统一的 OpenAI 兼容 LLM 实现

支持所有兼容 OpenAI API 的服务商（OpenAI, Claude via proxy, DeepSeek, Moonshot, 通义千问等），
通过 config.yaml 中的 base_url, api_key, model 参数配置。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import openai

from ainewssprite.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    """通用 OpenAI 兼容 API 调用。

    通过 config.yaml 的 llm 配置段或环境变量指定:
      - api_key / LLM_API_KEY 环境变量
      - base_url / LLM_BASE_URL 环境变量
      - model
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "gpt-4o",
        temperature: float = 0.3,
        batch_size: int = 8,
    ) -> None:
        resolved_key = api_key or os.environ.get("LLM_API_KEY", "")
        resolved_url = base_url or os.environ.get("LLM_BASE_URL", "")

        if not resolved_key:
            raise ValueError("请设置 LLM API Key (config.yaml llm.api_key 或 LLM_API_KEY 环境变量)")

        kwargs: dict[str, Any] = {"api_key": resolved_key}
        if resolved_url:
            kwargs["base_url"] = resolved_url

        self._client = openai.OpenAI(**kwargs)
        self._model = model
        self._temperature = temperature
        # 每条新闻约 200 token 响应，加 512 余量
        self._max_tokens = batch_size * 200 + 512

        logger.info("LLM provider: model=%s base_url=%s", model, resolved_url or "(default)")

    def chat(self, prompt: str, system: str = "") -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            messages=messages,
        )
        text = response.choices[0].message.content or ""
        logger.debug("[llm] 响应 (%d chars): %s...", len(text), text[:100])
        return text
