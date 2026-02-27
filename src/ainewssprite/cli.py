"""CLI 入口 -- 所有功能的编排中枢"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ainewssprite.config import (
    get_categories,
    get_db_path,
    get_http_config,
    get_llm_config,
    get_merge_window_days,
    get_output_dir,
    load_config,
)
from ainewssprite.db import NewsDB
from ainewssprite.llm.base import LLMProvider
from ainewssprite.llm.summarizer import Summarizer
from ainewssprite.models import RawNewsItem
from ainewssprite.output.json_export import export_json, write_json
from ainewssprite.output.markdown import generate_markdown, write_daily_markdown
from ainewssprite.processing.dedup import dedup_by_url
from ainewssprite.processing.merger import (
    build_match_prompt,
    build_merge_summary_prompt,
    parse_match_response,
)
from ainewssprite.sources.registry import create_sources
from ainewssprite.utils.http import PoliteClient

logger = logging.getLogger("ainewssprite")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ainewssprite",
        description="AI 新闻精灵 -- 每日 AI 领域新闻自动聚合工具",
    )
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--config", type=str, default="config.yaml", help="配置文件路径")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 摘要（仅采集）")
    parser.add_argument("--sources", nargs="+", help="仅运行指定的源 (e.g. hackernews techcrunch_ai)")
    parser.add_argument("--export", choices=["json", "md", "both"], help="从 DB 导出数据")
    parser.add_argument("--search", type=str, help="全文搜索历史事件")
    parser.add_argument("--top", nargs="?", const="软件工程师向", metavar="THEME",
                        help="回顾最近一周最符合主题的前 10 条新闻（默认主题: 软件工程师向）")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不保存文件")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    return parser


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_llm_provider(llm_config: dict[str, Any]) -> LLMProvider:
    """根据配置创建 LLM Provider (统一 OpenAI 兼容接口)。"""
    from ainewssprite.llm.openai import OpenAICompatProvider

    return OpenAICompatProvider(
        api_key=llm_config.get("api_key", ""),
        base_url=llm_config.get("base_url", ""),
        model=llm_config.get("model", "gpt-4o"),
        temperature=llm_config.get("temperature", 0.3),
        batch_size=llm_config.get("batch_size", 8),
    )


def run_fetch(
    config: dict[str, Any],
    sources_filter: list[str] | None,
) -> list[RawNewsItem]:
    """采集阶段: 从所有源采集新闻并去重。"""
    http_cfg = get_http_config(config)
    with PoliteClient(
        timeout=http_cfg["timeout"],
        delay=http_cfg["delay"],
        max_retries=http_cfg["max_retries"],
        user_agent=http_cfg["user_agent"],
    ) as client:
        sources = create_sources(config, client, only=sources_filter)
        logger.info("已注册 %d 个新闻源", len(sources))

        all_items: list[RawNewsItem] = []
        for source in sources:
            items = source.fetch()
            all_items.extend(items)

    logger.info("原始采集: %d 条", len(all_items))
    deduped = dedup_by_url(all_items)
    logger.info("URL 去重后: %d 条", len(deduped))
    return deduped


def run_process(
    items: list[RawNewsItem],
    db: NewsDB,
    config: dict[str, Any],
    no_llm: bool,
    dry_run: bool,
) -> set[int]:
    """处理阶段: 去重、摘要、合并、入库。返回本次新增/更新的事件 ID 集合。"""
    # 过滤掉 DB 中已存在的
    new_items = db.filter_new_items(items)
    logger.info("DB 去重后: %d 条新条目", len(new_items))

    if not new_items:
        logger.info("没有新条目需要处理")
        return set()

    now = datetime.now().isoformat()
    categories = get_categories(config)
    changed_event_ids: set[int] = set()

    if no_llm:
        # 不调用 LLM，直接入库（用原始标题做占位）
        for item in new_items:
            if dry_run:
                logger.info("[dry-run] 跳过入库: %s", item.title)
                continue
            event_id = db.insert_event(
                title_zh=item.title,
                summary_zh=item.description[:80] or item.title,
                category="events",
                tags=[],
                importance=3,
                now=now,
            )
            db.insert_article(item, event_id, now)
            changed_event_ids.add(event_id)
    else:
        llm_config = get_llm_config(config)
        provider = create_llm_provider(llm_config)
        summarizer = Summarizer(provider, categories, batch_size=llm_config["batch_size"])
        merge_window = get_merge_window_days(config)

        # 先做批量摘要
        results = summarizer.summarize(new_items)

        for result in results:
            raw: RawNewsItem = result["raw"]
            if dry_run:
                logger.info("[dry-run] %s -> %s", raw.title, result["title_zh"])
                continue

            # 查找相似事件
            recent_events = db.get_recent_events(merge_window)
            matched_event_id = None

            if recent_events:
                match_prompt = build_match_prompt(raw.title, raw.description, recent_events)
                try:
                    match_resp = provider.chat(match_prompt)
                    match_result = parse_match_response(match_resp)
                    if match_result["match"] and match_result["event_id"]:
                        matched_event_id = match_result["event_id"]
                except Exception as e:
                    logger.warning("相似匹配失败: %s", e)

            if matched_event_id:
                # 合并到已有事件
                existing = next((e for e in recent_events if e["id"] == matched_event_id), None)
                if existing:
                    try:
                        merge_prompt = build_merge_summary_prompt(
                            existing["summary_zh"], raw.title, raw.description
                        )
                        new_summary = provider.chat(merge_prompt)
                        db.update_event(
                            matched_event_id,
                            summary_zh=new_summary.strip(),
                            now=now,
                            tags=result["tags"],
                            importance=max(existing["importance"], result["importance"]),
                        )
                    except Exception as e:
                        logger.warning("合并摘要失败: %s", e)
                db.insert_article(raw, matched_event_id, now)
                changed_event_ids.add(matched_event_id)
                logger.info("合并到事件 #%d: %s", matched_event_id, raw.title[:50])
            else:
                # 创建新事件
                event_id = db.insert_event(
                    title_zh=result["title_zh"],
                    summary_zh=result["summary_zh"],
                    category=result["category"],
                    tags=result["tags"],
                    importance=result["importance"],
                    now=now,
                )
                db.insert_article(raw, event_id, now)
                changed_event_ids.add(event_id)
                logger.info("新事件 #%d: %s", event_id, result["title_zh"])

    return changed_event_ids


def run_export(
    db: NewsDB,
    config: dict[str, Any],
    date_str: str,
    export_type: str,
    dry_run: bool,
    no_llm: bool = False,
    event_ids: set[int] | None = None,
) -> None:
    """导出阶段: 从 DB 生成 Markdown / JSON。

    Args:
        event_ids: 如果指定，只导出这些事件。None 表示导出该日期所有事件。
    """
    output_dir = get_output_dir(config)
    categories = get_categories(config)

    if event_ids is not None:
        events = db.get_events_by_ids(event_ids)
    else:
        events = db.get_events_by_date(date_str)

    stats = db.get_stats(date_str)

    if not events:
        logger.info("日期 %s 没有事件数据", date_str)
        return

    articles_by_event = {ev["id"]: db.get_articles_for_event(ev["id"]) for ev in events}

    # 生成日报总结
    overview = ""
    if not no_llm and export_type in ("md", "both"):
        try:
            llm_config = get_llm_config(config)
            provider = create_llm_provider(llm_config)
            summarizer = Summarizer(provider, get_categories(config), batch_size=llm_config["batch_size"])
            logger.info("正在生成日报总结...")
            overview = summarizer.generate_daily_overview(events)
        except Exception as e:
            logger.warning("生成日报总结失败，跳过: %s", e)

    if export_type in ("md", "both"):
        md_content = generate_markdown(events, articles_by_event, categories, date_str, stats, overview=overview)
        if dry_run:
            print(md_content)
        else:
            path = write_daily_markdown(md_content, date_str, output_dir)
            logger.info("Markdown 日报已写入: %s", path)

    if export_type in ("json", "both"):
        data = export_json(db, date_str=date_str)
        if dry_run:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            json_path = Path(output_dir) / dt.strftime("%Y") / dt.strftime("%m") / (dt.strftime("%Y%m%d") + ".json")
            write_json(data, json_path)
            logger.info("JSON 已写入: %s", json_path)


def run_search(db: NewsDB, query: str) -> None:
    """搜索历史事件。"""
    events = db.search_events(query)
    if not events:
        print(f"没有找到匹配 '{query}' 的事件")
        return

    print(f"找到 {len(events)} 条匹配事件:\n")
    for ev in events:
        tags = json.loads(ev["tags"]) if isinstance(ev["tags"], str) else ev.get("tags", [])
        tag_str = ", ".join(tags)
        print(f"  [{ev['category']}] {ev['title_zh']}")
        print(f"    摘要: {ev['summary_zh'][:80]}")
        print(f"    标签: {tag_str}")
        print(f"    时间: {ev['first_seen'][:10]} | 来源数: {ev['source_count']}")
        print()


def run_weekly_top(db: NewsDB, config: dict[str, Any], theme: str) -> None:
    """回顾最近一周最符合主题的前 10 条新闻。"""
    events = db.get_recent_events(7)
    if not events:
        print("最近 7 天没有事件数据")
        return

    llm_config = get_llm_config(config)
    provider = create_llm_provider(llm_config)
    summarizer = Summarizer(provider, get_categories(config), batch_size=llm_config["batch_size"])

    logger.info("正在从 %d 条事件中筛选「%s」主题 Top 10...", len(events), theme)
    ranked_ids = summarizer.rank_by_theme(events, theme, top_n=10)

    if not ranked_ids:
        print("未能筛选出相关事件")
        return

    # 按排名顺序取出事件
    events_map = {ev["id"]: ev for ev in events}
    ranked_events = [events_map[eid] for eid in ranked_ids if eid in events_map]

    print(f"\n## 周度回顾 | 主题: {theme} | Top {len(ranked_events)}\n")
    for rank, ev in enumerate(ranked_events, 1):
        tags = json.loads(ev["tags"]) if isinstance(ev["tags"], str) else ev.get("tags", [])
        tag_str = " ".join(f"`{t}`" for t in tags) if tags else ""
        importance_stars = "*" * ev.get("importance", 3)
        date_str = ev.get("first_seen", "")[:10]
        articles = db.get_articles_for_event(ev["id"])
        source_str = ", ".join(a["source"] for a in articles[:3])

        print(f"**{rank}. {ev['title_zh']}** [{importance_stars}]")
        print(f"   {ev['summary_zh']}")
        if source_str:
            print(f"   来源: {source_str} | {date_str} | 报道数: {ev.get('source_count', 1)}")
        if articles:
            for a in articles:
                print(f"   - {a['url']}")
        if tag_str:
            print(f"   标签: {tag_str}")
        print()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)

    # 确定配置文件路径
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error("配置加载失败: %s", e)
        sys.exit(1)

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    db_path = get_db_path(config)
    if not db_path.is_absolute():
        db_path = config_path.parent / db_path

    with NewsDB(db_path) as db:
        # 搜索模式
        if args.search:
            run_search(db, args.search)
            return

        # 周度主题回顾
        if args.top is not None:
            run_weekly_top(db, config, args.top)
            return

        # 仅导出模式
        if args.export:
            run_export(db, config, date_str, args.export, args.dry_run, no_llm=args.no_llm)
            return

        # 完整流程: 采集 → 处理 → 导出
        items = run_fetch(config, args.sources)

        if not items:
            logger.info("没有采集到任何新闻")
            return

        changed_ids = run_process(items, db, config, args.no_llm, args.dry_run)
        logger.info("新增/更新 %d 个事件", len(changed_ids))

        # 自动导出今日日报 (默认只输出 Markdown，仅包含本次新增/更新的事件)
        if not args.dry_run and changed_ids:
            run_export(db, config, date_str, "md", dry_run=False, no_llm=args.no_llm, event_ids=changed_ids)


if __name__ == "__main__":
    main()
