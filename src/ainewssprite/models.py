"""数据模型定义 -- 全项目数据契约"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class RawNewsItem:
    """原始新闻条目 -- 来自采集器的未处理数据"""

    title: str
    url: str
    source: str
    published_at: Optional[datetime] = None
    description: str = ""
    author: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class ProcessedNewsItem:
    """处理后的新闻条目 -- 包含 LLM 生成的中文摘要"""

    raw: RawNewsItem
    title_zh: str
    summary_zh: str
    category: str
    tags: tuple[str, ...] = ()
    importance: int = 3
    event_id: Optional[int] = None


@dataclass(frozen=True)
class DailyDigest:
    """每日日报"""

    date: str
    items: tuple[ProcessedNewsItem, ...]
    generated_at: str
    source_stats: dict[str, int] = field(default_factory=dict)
