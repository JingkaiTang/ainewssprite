"""URL 精确去重"""

from __future__ import annotations

from typing import Sequence

from ainewssprite.models import RawNewsItem


def dedup_by_url(items: Sequence[RawNewsItem]) -> list[RawNewsItem]:
    """按 URL 去重，保留首次出现的条目。"""
    seen: set[str] = set()
    result: list[RawNewsItem] = []
    for item in items:
        url = item.url.rstrip("/")
        if url not in seen:
            seen.add(url)
            result.append(item)
    return result
