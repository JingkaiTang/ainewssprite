"""配置驱动的新闻源注册表"""

from __future__ import annotations

from typing import Any

from ainewssprite.config import get_enabled_rss_sources, get_hackernews_config
from ainewssprite.sources.base import NewsSource
from ainewssprite.sources.hackernews import HackerNewsSource
from ainewssprite.sources.rss import RSSSource
from ainewssprite.utils.http import PoliteClient


def create_sources(
    config: dict[str, Any],
    client: PoliteClient,
    only: list[str] | None = None,
) -> list[NewsSource]:
    """根据配置创建所有启用的新闻源实例。

    Args:
        config: 完整配置字典
        client: HTTP 客户端
        only: 如果指定，只创建这些名称的源
    """
    sources: list[NewsSource] = []

    for rss_cfg in get_enabled_rss_sources(config):
        name = rss_cfg["name"]
        if only and name not in only:
            continue
        sources.append(
            RSSSource(
                source_name=name,
                url=rss_cfg["url"],
                client=client,
                keywords=rss_cfg.get("keywords"),
            )
        )

    hn_cfg = get_hackernews_config(config)
    if hn_cfg and (not only or "hackernews" in only or "hn" in only):
        sources.append(
            HackerNewsSource(
                client=client,
                search_keywords=hn_cfg.get("search_keywords"),
                min_points=hn_cfg.get("min_points", 50),
                max_items=hn_cfg.get("max_items", 20),
            )
        )

    return sources
