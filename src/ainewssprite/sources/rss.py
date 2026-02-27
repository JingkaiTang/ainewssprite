"""RSS 通用采集器"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import feedparser
from dateutil import parser as dateparser

from ainewssprite.models import RawNewsItem
from ainewssprite.sources.base import NewsSource
from ainewssprite.utils.http import PoliteClient
from ainewssprite.utils.text import clean_html, compute_content_hash

logger = logging.getLogger(__name__)

_WECHAT_CT_RE = re.compile(r'var\s+ct\s*=\s*"(\d{10})"')


class RSSSource(NewsSource):
    """通用 RSS 源采集器，配置驱动。"""

    def __init__(
        self,
        source_name: str,
        url: str,
        client: PoliteClient,
        keywords: list[str] | None = None,
        max_age_days: int = 3,
    ) -> None:
        self._name = source_name
        self._url = url
        self._client = client
        self._keywords = [k.lower() for k in (keywords or [])]
        self._max_age_days = max_age_days

    @property
    def name(self) -> str:
        return self._name

    def fetch(self) -> Sequence[RawNewsItem]:
        try:
            return self._do_fetch()
        except Exception as e:
            logger.error("[%s] 采集失败: %s", self._name, e)
            return []

    def _do_fetch(self) -> list[RawNewsItem]:
        logger.info("[%s] 正在采集 %s", self._name, self._url)
        resp = self._client.get(self._url)
        feed = feedparser.parse(resp.text)

        if feed.bozo and not feed.entries:
            logger.warning("[%s] RSS 解析异常: %s", self._name, feed.bozo_exception)
            return []

        # 解析 feed 级别的日期，用于微信等无日期源的回退
        feed_date = self._parse_feed_date(feed)

        cutoff = datetime.now(timezone.utc) - timedelta(days=self._max_age_days)
        items: list[RawNewsItem] = []
        for entry in feed.entries:
            item = self._parse_entry(entry, feed_date)
            if item is None:
                continue
            if item.published_at and item.published_at.tzinfo and item.published_at < cutoff:
                continue
            if self._keywords and not self._matches_keywords(item):
                continue
            items.append(item)

        logger.info("[%s] 采集到 %d 条新闻", self._name, len(items))
        return items

    def _parse_entry(self, entry: Any, feed_date: datetime | None) -> RawNewsItem | None:
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not title or not link:
            return None

        description = clean_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        author = getattr(entry, "author", "") or ""
        published_at = self._parse_date(entry)

        # 微信文章缺少日期时，尝试从文章页面提取
        if published_at is None and "mp.weixin.qq.com" in link:
            published_at = self._fetch_wechat_date(link)
            # 仍然失败则用 feed 构建日期回退
            if published_at is None and feed_date is not None:
                published_at = feed_date

        return RawNewsItem(
            title=title,
            url=link,
            source=self._name,
            published_at=published_at,
            description=description,
            author=author,
            content_hash=compute_content_hash(title, link),
        )

    def _matches_keywords(self, item: RawNewsItem) -> bool:
        text = f"{item.title} {item.description}".lower()
        return any(kw in text for kw in self._keywords)

    def _fetch_wechat_date(self, url: str) -> datetime | None:
        """从微信文章页面提取 var ct 时间戳。

        仅对短链接 (/s/xxx) 格式有效，长链接 (__biz=&mid=&sn=) 会被微信
        captcha 拦截。因此先尝试抓取，失败时静默返回 None。
        """
        try:
            resp = self._client.get(url)
            m = _WECHAT_CT_RE.search(resp.text)
            if m:
                ts = int(m.group(1))
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                logger.debug("[%s] 微信文章日期: %s -> %s", self._name, url[:60], dt.date())
                return dt
        except Exception as e:
            logger.debug("[%s] 提取微信日期失败: %s", self._name, e)
        return None

    @staticmethod
    def _parse_feed_date(feed: Any) -> datetime | None:
        """解析 feed 级别的 lastBuildDate / updated。"""
        for attr in ("updated", "published"):
            raw = getattr(feed.feed, attr, None)
            if raw:
                try:
                    return dateparser.parse(raw)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_date(entry: Any) -> datetime | None:
        for attr in ("published", "updated", "created"):
            raw = getattr(entry, attr, None)
            if raw:
                try:
                    return dateparser.parse(raw)
                except (ValueError, TypeError):
                    continue
        return None
