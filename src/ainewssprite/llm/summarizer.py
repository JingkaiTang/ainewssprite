"""批量摘要 + 分类"""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from ainewssprite.llm.base import LLMProvider
from ainewssprite.models import RawNewsItem

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "你是一个专业的 AI 领域新闻编辑，负责对 AI 相关新闻进行中文摘要、分类和重要性评估。"


def build_batch_prompt(items: Sequence[RawNewsItem], categories: dict[str, Any]) -> str:
    """构建批量摘要 Prompt。"""
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


def parse_batch_response(
    response_text: str,
    items: Sequence[RawNewsItem],
) -> list[dict[str, Any]]:
    """解析 LLM 批量摘要响应。"""
    text = response_text.strip()

    # 提取 JSON 数组
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    try:
        results = json.loads(text)
    except json.JSONDecodeError:
        logger.error("无法解析 LLM 批量响应: %s", text[:300])
        return []

    if not isinstance(results, list):
        logger.error("LLM 响应不是数组: %s", type(results))
        return []

    parsed: list[dict[str, Any]] = []
    for r in results:
        idx = r.get("index", 0) - 1
        if 0 <= idx < len(items):
            parsed.append({
                "raw": items[idx],
                "title_zh": r.get("title_zh", ""),
                "summary_zh": r.get("summary_zh", ""),
                "category": r.get("category", "events"),
                "tags": r.get("tags", []),
                "importance": r.get("importance", 3),
            })
    return parsed


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
        """批量处理新闻条目，返回处理结果列表。"""
        all_results: list[dict[str, Any]] = []

        for i in range(0, len(items), self._batch_size):
            batch = items[i : i + self._batch_size]
            logger.info("处理批次 %d-%d / %d", i + 1, i + len(batch), len(items))

            prompt = build_batch_prompt(batch, self._categories)
            try:
                response = self._provider.chat(prompt, system=SYSTEM_PROMPT)
                results = parse_batch_response(response, batch)
                all_results.extend(results)
            except Exception as e:
                logger.error("LLM 批量摘要失败: %s", e)
                # 对失败的批次生成占位结果
                for item in batch:
                    all_results.append({
                        "raw": item,
                        "title_zh": item.title,
                        "summary_zh": item.description[:80] or item.title,
                        "category": "events",
                        "tags": [],
                        "importance": 3,
                    })

        return all_results

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
