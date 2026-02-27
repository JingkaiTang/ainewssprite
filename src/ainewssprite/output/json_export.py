"""JSON 导出 -- 从 SQLite 导出结构化数据供工具消费"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ainewssprite.db import NewsDB


def export_json(
    db: NewsDB,
    date_str: str | None = None,
    search_query: str | None = None,
) -> dict[str, Any]:
    """从数据库导出 JSON 格式数据。"""
    query_info: dict[str, Any] = {}

    if search_query:
        events = db.search_events(search_query)
        query_info["search"] = search_query
    elif date_str:
        events = db.get_events_by_date(date_str)
        query_info["date"] = date_str
    else:
        events = db.get_events_by_date(datetime.now().strftime("%Y-%m-%d"))
        query_info["date"] = datetime.now().strftime("%Y-%m-%d")

    event_list = []
    for ev in events:
        articles = db.get_articles_for_event(ev["id"])
        tags = json.loads(ev["tags"]) if isinstance(ev["tags"], str) else ev.get("tags", [])
        event_list.append({
            "id": ev["id"],
            "title_zh": ev["title_zh"],
            "summary_zh": ev["summary_zh"],
            "category": ev["category"],
            "tags": tags,
            "importance": ev["importance"],
            "first_seen": ev["first_seen"],
            "last_updated": ev["last_updated"],
            "source_count": ev["source_count"],
            "articles": [
                {
                    "title": a["title"],
                    "url": a["url"],
                    "source": a["source"],
                    "published_at": a.get("published_at"),
                }
                for a in articles
            ],
        })

    return {
        "exported_at": datetime.now().isoformat(),
        "query": query_info,
        "total_events": len(event_list),
        "events": event_list,
    }


def write_json(data: dict[str, Any], path: str | Path) -> Path:
    """写入 JSON 文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
