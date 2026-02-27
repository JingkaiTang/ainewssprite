"""Hacker News Algolia API 采集器"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Sequence

from ainewssprite.models import RawNewsItem
from ainewssprite.sources.base import NewsSource
from ainewssprite.utils.http import PoliteClient
from ainewssprite.utils.text import clean_html, compute_content_hash

logger = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


class HackerNewsSource(NewsSource):
    """Hacker News 采集器，使用 Algolia 搜索 API。"""

    def __init__(
        self,
        client: PoliteClient,
        search_keywords: list[str] | None = None,
        min_points: int = 50,
        max_items: int = 20,
    ) -> None:
        self._client = client
        self._keywords = search_keywords or ["AI", "LLM", "GPT", "machine learning"]
        self._min_points = min_points
        self._max_items = max_items

    @property
    def name(self) -> str:
        return "hackernews"

    def fetch(self) -> Sequence[RawNewsItem]:
        try:
            return self._do_fetch()
        except Exception as e:
            logger.error("[hackernews] 采集失败: %s", e)
            return []

    def _do_fetch(self) -> list[RawNewsItem]:
        cutoff = int(time.time()) - 86400  # 过去 24 小时
        seen_ids: set[str] = set()
        all_hits: list[dict[str, Any]] = []

        for keyword in self._keywords:
            logger.info("[hackernews] 搜索关键词: %s", keyword)
            resp = self._client.get(
                HN_SEARCH_URL,
                params={
                    "query": keyword,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{cutoff},points>{self._min_points}",
                    "hitsPerPage": 50,
                },
            )
            data = resp.json()
            for hit in data.get("hits", []):
                obj_id = hit.get("objectID", "")
                if obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    all_hits.append(hit)

        all_hits.sort(key=lambda h: h.get("points", 0), reverse=True)
        all_hits = all_hits[: self._max_items]

        items = [self._parse_hit(hit) for hit in all_hits]
        items = [i for i in items if i is not None]

        logger.info("[hackernews] 采集到 %d 条新闻", len(items))
        return items

    def _parse_hit(self, hit: dict[str, Any]) -> RawNewsItem | None:
        title = hit.get("title", "").strip()
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        if not title:
            return None

        points = hit.get("points", 0)
        num_comments = hit.get("num_comments", 0)
        author = hit.get("author", "")

        created_at = None
        if hit.get("created_at"):
            try:
                created_at = datetime.fromisoformat(hit["created_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        description = clean_html(hit.get("story_text", "") or "")
        if not description:
            description = f"Points: {points} | Comments: {num_comments}"

        return RawNewsItem(
            title=title,
            url=url,
            source="hackernews",
            published_at=created_at,
            description=description,
            author=author,
            content_hash=compute_content_hash(title, url),
        )
