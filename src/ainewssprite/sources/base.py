"""新闻源抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ainewssprite.models import RawNewsItem


class NewsSource(ABC):
    """新闻源采集器抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """源标识名称。"""
        ...

    @abstractmethod
    def fetch(self) -> Sequence[RawNewsItem]:
        """采集新闻，返回原始条目列表。

        单个源的异常应内部处理，失败时返回空列表而非抛出异常。
        """
        ...
