"""礼貌的 HTTP 客户端 -- 带限速、重试和超时"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class PoliteClient:
    """封装 httpx，提供每域名限速、自动重试和统一超时。"""

    def __init__(
        self,
        timeout: int = 30,
        delay: float = 1.0,
        max_retries: int = 3,
        user_agent: str = "ainewssprite/1.0",
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        self._delay = delay
        self._max_retries = max_retries
        self._last_request: dict[str, float] = defaultdict(float)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET 请求，带域名限速和重试。"""
        domain = urlparse(url).netloc
        self._rate_limit(domain)

        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.get(url, **kwargs)
                resp.raise_for_status()
                self._last_request[domain] = time.monotonic()
                return resp
            except httpx.HTTPStatusError as e:
                last_exc = e
                # 4xx 客户端错误不重试（404/403 等不会因重试而改变）
                if 400 <= e.response.status_code < 500:
                    logger.error("请求失败 %s: %s", url, e)
                    raise
                if attempt < self._max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("请求失败 %s (尝试 %d/%d), %s秒后重试: %s", url, attempt, self._max_retries, wait, e)
                    time.sleep(wait)
                else:
                    logger.error("请求最终失败 %s: %s", url, e)
            except httpx.TransportError as e:
                last_exc = e
                if attempt < self._max_retries:
                    wait = 2 ** (attempt - 1)
                    logger.warning("请求失败 %s (尝试 %d/%d), %s秒后重试: %s", url, attempt, self._max_retries, wait, e)
                    time.sleep(wait)
                else:
                    logger.error("请求最终失败 %s: %s", url, e)

        raise last_exc  # type: ignore[misc]

    def _rate_limit(self, domain: str) -> None:
        elapsed = time.monotonic() - self._last_request[domain]
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
