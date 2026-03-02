"""批量摘要 + 分类"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from ainewssprite.llm.base import LLMProvider
from ainewssprite.models import RawNewsItem
from ainewssprite.utils.text import is_chinese

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "你是一个专业的 AI 领域新闻编辑，负责对 AI 相关新闻进行中文摘要、分类和重要性评估。"


def build_batch_prompt(items: Sequence[RawNewsItem], categories: dict[str, Any]) -> str:
    """构建批量摘要 Prompt（用于非中文条目，需要翻译）。"""
    cat_list = ", ".join(categories.keys())

    news_lines = []
    for i, item in enumerate(items, 1):
        news_lines.append(f"{i}. 标题: {item.title}\n   来源: {item.source}\n   描述: {item.description[:200]}")

    news_text = "\n\n".join(news_lines)

    return f"""请对以下 {len(items)} 条 AI 领域新闻进行处理:

{news_text}

对每条新闻:
1. 生成一个不超过 30 字的中文标题
2. 生成不超过 80 字的中文摘要
3. 分类到以下类别之一: {cat_list}
4. 提取 1-3 个中文关键词标签
5. 评估重要性 (1-5, 5为最重要)

严格按以下 JSON 数组格式输出，不要输出其他内容:
[
  {{
    "index": 1,
    "title_zh": "中文标题",
    "summary_zh": "中文摘要",
    "category": "分类",
    "tags": ["标签1", "标签2"],
    "importance": 3
  }}
]"""


def build_classify_prompt(items: Sequence[RawNewsItem], categories: dict[str, Any]) -> str:
    """构建分类 Prompt（用于已经是中文的条目，无需翻译）。"""
    cat_list = ", ".join(categories.keys())

    news_lines = []
    for i, item in enumerate(items, 1):
        news_lines.append(f"{i}. 标题: {item.title}\n   描述: {item.description[:200]}")

    news_text = "\n\n".join(news_lines)

    return f"""以下 {len(items)} 条新闻已经是中文，请仅做分类和评估（不需要翻译）:

{news_text}

对每条新闻:
1. 分类到以下类别之一: {cat_list}
2. 提取 1-3 个关键词标签
3. 评估重要性 (1-5, 5为最重要)

严格按以下 JSON 数组格式输出，不要输出其他内容:
[
  {{
    "index": 1,
    "category": "分类",
    "tags": ["标签1", "标签2"],
    "importance": 3
  }}
]"""


def _fix_json(text: str) -> str:
    """尝试修复常见的 JSON 格式问题。"""
    import re
    # 去掉 markdown 代码块标记
    text = re.sub(r"```(?:json)?\s*", "", text)
    # 去掉行尾多余逗号 (], 前 / }, 前)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 修复未转义的换行符（JSON 字符串内部）
    text = re.sub(r'(?<=": ")(.*?)(?=")', lambda m: m.group(0).replace("\n", "\\n"), text)
    return text


def _try_parse_json(text: str) -> Any:
    """多策略 JSON 解析：原文 → 提取数组 → 修复后重试 → 提取对象 → 逐行提取。"""
    # 1) 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) 提取最外层 [] (优先，因为批量响应通常是数组)
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # 3) 修复常见格式问题（尾逗号、markdown 代码块等）后重试数组
    fixed = _fix_json(text)
    start = fixed.find("[")
    end = fixed.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(fixed[start : end + 1])
        except json.JSONDecodeError:
            pass

    # 4) 提取 {} 对象 (原文和修复后都试)
    for src in [text, fixed]:
        start = src.find("{")
        end = src.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(src[start : end + 1])
            except json.JSONDecodeError:
                pass

    # 5) 逐行提取独立的 JSON 对象
    import re
    objects = []
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            objects.append(json.loads(m.group()))
        except json.JSONDecodeError:
            continue
    if objects:
        return objects

    return None


def parse_batch_response(
    response_text: str,
    items: Sequence[RawNewsItem],
) -> list[dict[str, Any]]:
    """解析 LLM 批量摘要响应，多策略容错。"""
    text = response_text.strip()

    result = _try_parse_json(text)

    if result is None:
        logger.error("无法解析 LLM 批量响应: %s", text[:300])
        return []

    # 如果返回的是单个 dict，包装成列表
    if isinstance(result, dict):
        result = [result]

    if not isinstance(result, list):
        logger.error("LLM 响应不是数组: %s", type(result))
        return []

    parsed: list[dict[str, Any]] = []
    for r in result:
        if not isinstance(r, dict):
            continue
        idx = _safe_int(r.get("index"), 0) - 1
        if 0 <= idx < len(items):
            item = items[idx]
            tags = r.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            elif not isinstance(tags, list):
                tags = []
            parsed.append({
                "raw": item,
                "title_zh": str(r.get("title_zh", "") or item.title),
                "summary_zh": str(r.get("summary_zh", "") or item.description[:80] or item.title),
                "category": str(r.get("category", "") or "events"),
                "tags": tags,
                "importance": _safe_int(r.get("importance"), 3),
            })

    # 对于未解析到的条目，用 index 位置猜测匹配
    parsed_indices = {_safe_int(r.get("index"), 0) - 1 for r in result if isinstance(r, dict)}
    if len(parsed) < len(result):
        for seq, r in enumerate(result):
            if not isinstance(r, dict):
                continue
            idx = _safe_int(r.get("index"), 0) - 1
            if idx < 0 or idx >= len(items):
                # index 缺失或越界，尝试用序号作为 index
                if 0 <= seq < len(items) and seq not in parsed_indices:
                    item = items[seq]
                    tags = r.get("tags", [])
                    if isinstance(tags, str):
                        tags = [t.strip() for t in tags.split(",") if t.strip()]
                    elif not isinstance(tags, list):
                        tags = []
                    parsed.append({
                        "raw": item,
                        "title_zh": str(r.get("title_zh", "") or item.title),
                        "summary_zh": str(r.get("summary_zh", "") or item.description[:80] or item.title),
                        "category": str(r.get("category", "") or "events"),
                        "tags": tags,
                        "importance": _safe_int(r.get("importance"), 3),
                    })
                    parsed_indices.add(seq)
                    logger.warning("条目 index=%s 越界，按序号 %d 匹配", r.get("index"), seq + 1)

    return parsed


def _safe_int(value: Any, default: int = 0) -> int:
    """安全地将值转为 int。"""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    return default


class Summarizer:
    """新闻摘要生成器，支持批量处理。"""

    def __init__(
        self,
        provider: LLMProvider,
        categories: dict[str, Any],
        batch_size: int = 8,
    ) -> None:
        self._provider = provider
        self._categories = categories
        self._batch_size = batch_size

    def summarize(self, items: Sequence[RawNewsItem]) -> list[dict[str, Any]]:
        """批量处理新闻条目。中文条目只做分类，非中文条目做翻译+摘要。"""
        # 按语言分组
        zh_items: list[RawNewsItem] = []
        other_items: list[RawNewsItem] = []
        for item in items:
            if is_chinese(item.title):
                zh_items.append(item)
            else:
                other_items.append(item)

        logger.info("条目分布: %d 条中文, %d 条非中文", len(zh_items), len(other_items))

        all_results: list[dict[str, Any]] = []

        # 中文条目: 仅分类+打标签
        all_results.extend(self._process_chinese(zh_items))

        # 非中文条目: 翻译+摘要+分类
        all_results.extend(self._process_translate(other_items))

        return all_results

    def _process_chinese(self, items: Sequence[RawNewsItem]) -> list[dict[str, Any]]:
        """处理中文条目: 用原标题/描述，只调 LLM 做分类。"""
        results: list[dict[str, Any]] = []

        for i in range(0, len(items), self._batch_size):
            batch = items[i : i + self._batch_size]
            logger.info("分类中文批次 %d-%d / %d", i + 1, i + len(batch), len(items))

            prompt = build_classify_prompt(batch, self._categories)
            try:
                response = self._provider.chat(prompt, system=SYSTEM_PROMPT)
                parsed = parse_batch_response(response, batch)
                # 用原始标题和描述覆盖（LLM 只返回了分类）
                for p in parsed:
                    raw: RawNewsItem = p["raw"]
                    p["title_zh"] = raw.title
                    p["summary_zh"] = raw.description[:80] or raw.title
                results.extend(parsed)
            except Exception as e:
                logger.error("中文分类失败: %s", e)
                for item in batch:
                    results.append({
                        "raw": item,
                        "title_zh": item.title,
                        "summary_zh": item.description[:80] or item.title,
                        "category": "events",
                        "tags": [],
                        "importance": 3,
                    })

        return results

    def _process_translate(self, items: Sequence[RawNewsItem]) -> list[dict[str, Any]]:
        """处理非中文条目: 翻译+摘要+分类。"""
        results: list[dict[str, Any]] = []

        for i in range(0, len(items), self._batch_size):
            batch = items[i : i + self._batch_size]
            logger.info("翻译摘要批次 %d-%d / %d", i + 1, i + len(batch), len(items))

            prompt = build_batch_prompt(batch, self._categories)
            try:
                response = self._provider.chat(prompt, system=SYSTEM_PROMPT)
                results.extend(parse_batch_response(response, batch))
            except Exception as e:
                logger.error("LLM 批量摘要失败: %s", e)
                for item in batch:
                    results.append({
                        "raw": item,
                        "title_zh": item.title,
                        "summary_zh": item.description[:80] or item.title,
                        "category": "events",
                        "tags": [],
                        "importance": 3,
                    })

        return results

    def generate_daily_overview(self, events: list[dict[str, Any]]) -> str:
        """根据当天所有事件生成日报总结（重点看点 + 趋势）。"""
        if not events:
            return ""

        event_lines = []
        for ev in events:
            event_lines.append(f"- [{ev.get('category', '')}] {ev['title_zh']}: {ev['summary_zh']}")

        events_text = "\n".join(event_lines)

        prompt = f"""以下是今天的 AI 领域新闻事件列表:

{events_text}

请生成今日看点，严格按以下 Markdown 格式输出:

- **关键词短语**: 一句话说明（不超过 30 字）
- **关键词短语**: 一句话说明（不超过 30 字）
- ...

要求:
1. 提取 3-5 条最值得关注的看点，每条一个列表项
2. 每条以 **加粗关键词** 开头，后接冒号和简短说明
3. 如果能看出趋势，最后一条写趋势观察
4. 中文输出，不要套话，不要输出标题

示例格式:
- **Nvidia 财报创新高**: 数据中心收入暴涨，CEO 称 token 需求呈指数级增长
- **Anthropic 收购 Vercept**: 加码 computer-use 智能体能力，强化工具使用生态
- **趋势**: 多家大厂本周密集发布智能体相关产品，AI Agent 落地加速"""

        try:
            overview = self._provider.chat(prompt, system=SYSTEM_PROMPT)
            return overview.strip()
        except Exception as e:
            logger.warning("生成日报总结失败: %s", e)
            return ""

    def rank_by_theme(
        self,
        events: list[dict[str, Any]],
        theme: str,
        top_n: int = 10,
    ) -> list[int]:
        """根据主题对事件排序，返回最相关的 top_n 个事件 ID（按相关度降序）。"""
        if not events:
            return []

        event_lines = []
        for ev in events:
            tags_str = ev.get("tags", "[]")
            if isinstance(tags_str, str):
                try:
                    tags = json.loads(tags_str)
                except json.JSONDecodeError:
                    tags = []
            else:
                tags = tags_str
            event_lines.append(
                f"ID={ev['id']} | 分类={ev.get('category', '')} | "
                f"标签={','.join(tags)} | 来源数={ev.get('source_count', 1)} | "
                f"标题: {ev['title_zh']}\n  摘要: {ev['summary_zh']}"
            )

        events_text = "\n".join(event_lines)

        prompt = f"""以下是最近一周的 AI 领域新闻事件列表:

{events_text}

请从中筛选出最符合「{theme}」主题的前 {top_n} 条新闻，按相关度从高到低排序。

评判标准:
1. 与「{theme}」主题的相关度（最重要）
2. 新闻本身的重要性和影响力
3. 多源报道的事件优先

严格按以下 JSON 数组格式输出，不要输出其他内容:
[{{"id": 事件ID}}, {{"id": 事件ID}}, ...]

只输出 ID 列表，最多 {top_n} 条。"""

        try:
            response = self._provider.chat(prompt, system=SYSTEM_PROMPT)
            result = _try_parse_json(response.strip())
            if result is None:
                raise ValueError(f"无法解析响应: {response[:200]}")
            if isinstance(result, dict) and "id" in result:
                result = [result]
            if not isinstance(result, list):
                raise ValueError(f"响应不是数组: {type(result)}")
            ids = []
            for item in result:
                if isinstance(item, dict):
                    eid = _safe_int(item.get("id"), -1)
                    if eid > 0:
                        ids.append(eid)
                elif isinstance(item, (int, float)):
                    ids.append(int(item))
            return ids[:top_n]
        except Exception as e:
            logger.error("主题排序失败: %s", e)
            # 降级: 按 importance 排序返回
            sorted_events = sorted(events, key=lambda e: e.get("importance", 0), reverse=True)
            return [e["id"] for e in sorted_events[:top_n]]
