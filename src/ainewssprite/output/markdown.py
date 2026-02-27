"""Markdown 日报生成"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def generate_markdown(
    events: list[dict[str, Any]],
    articles_by_event: dict[int, list[dict[str, Any]]],
    categories: dict[str, dict[str, str]],
    date_str: str,
    stats: dict[str, Any],
    overview: str = "",
) -> str:
    """生成 Markdown 格式的日报。"""
    lines: list[str] = []
    lines.append(f"# AI 新闻日报 {date_str}")
    lines.append("")
    lines.append("> 自动聚合 AI 领域最新资讯")
    lines.append("")

    if overview:
        lines.append("## 今日看点")
        lines.append("")
        lines.append(overview)
        lines.append("")

    lines.append("---")
    lines.append("")

    # 按分类组织
    events_by_cat: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        cat = ev["category"]
        events_by_cat.setdefault(cat, []).append(ev)

    for cat_key, cat_info in categories.items():
        cat_events = events_by_cat.get(cat_key, [])
        if not cat_events:
            continue

        cat_name = cat_info.get("name", cat_key)
        lines.append(f"## {cat_name}")
        lines.append("")

        for ev in cat_events:
            importance_stars = "*" * ev.get("importance", 3)
            first_seen = ev.get("first_seen", "")[:10]
            lines.append(f"### {ev['title_zh']} [{importance_stars}]")
            lines.append("")
            lines.append(f"> {first_seen}")
            lines.append("")
            lines.append(f"{ev['summary_zh']}")
            lines.append("")

            # 来源链接
            articles = articles_by_event.get(ev["id"], [])
            if articles:
                lines.append("**来源:**")
                for art in articles:
                    pub = (art.get("published_at") or art.get("fetched_at") or "")[:10]
                    if pub:
                        lines.append(f"- [{art['source']}]({art['url']}) | {pub}")
                    else:
                        lines.append(f"- [{art['source']}]({art['url']})")
                lines.append("")

            # 标签
            tags = json.loads(ev["tags"]) if isinstance(ev["tags"], str) else ev.get("tags", [])
            if tags:
                tag_str = " ".join(f"`{t}`" for t in tags)
                lines.append(f"**标签:** {tag_str}")
                lines.append("")

            lines.append("---")
            lines.append("")

    # 统计
    lines.append(f"*共收录 {stats.get('event_count', 0)} 条事件，{stats.get('article_count', 0)} 篇报道*")
    source_stats = stats.get("sources", {})
    if source_stats:
        src_parts = [f"{k}: {v}" for k, v in source_stats.items()]
        lines.append(f"*来源分布: {', '.join(src_parts)}*")
    lines.append(f"*生成时间: {datetime.now().isoformat()}*")

    return "\n".join(lines)


def write_daily_markdown(
    content: str,
    date_str: str,
    output_dir: str | Path,
) -> Path:
    """写入每日 Markdown 文件到 YYYY/MM/YYYYMMDD.md 路径。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year = dt.strftime("%Y")
    month = dt.strftime("%m")
    filename = dt.strftime("%Y%m%d") + ".md"

    path = Path(output_dir) / year / month / filename
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        import logging

        logging.getLogger(__name__).error("写入 Markdown 日报失败 %s: %s", path, e)
        raise
    return path
