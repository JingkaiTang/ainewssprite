"""LLM 驱动的相似新闻合并"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def build_match_prompt(
    new_title: str,
    new_description: str,
    candidates: list[dict[str, Any]],
) -> str:
    """构建 LLM 相似判断的 Prompt。"""
    candidate_lines = []
    for c in candidates:
        candidate_lines.append(f"- ID={c['id']}: {c['title_zh']} ({c['summary_zh'][:80]}...)")

    candidates_text = "\n".join(candidate_lines) if candidate_lines else "(无候选事件)"

    return f"""你是一个新闻编辑，请判断以下新条目是否在报道已知事件列表中的某个事件。

新条目:
标题: {new_title}
描述: {new_description[:300]}

已知事件列表:
{candidates_text}

请严格按 JSON 格式回答:
- 如果新条目报道的是某个已知事件，返回: {{"match": true, "event_id": <对应事件ID>}}
- 如果是全新事件，返回: {{"match": false, "event_id": null}}

仅输出 JSON，不要输出其他内容。"""


def build_merge_summary_prompt(
    existing_summary: str,
    new_title: str,
    new_description: str,
) -> str:
    """构建合并摘要的 Prompt。"""
    return f"""你是一个专业的 AI 领域新闻编辑。以下是同一事件的已有摘要和新报道，请生成更新后的中文摘要。

已有摘要:
{existing_summary}

新报道:
标题: {new_title}
描述: {new_description[:500]}

要求:
1. 合并新旧信息，不超过 100 字
2. 保留关键事实，去除重复
3. 中文输出

仅输出更新后的摘要文本，不要输出其他内容。"""


def parse_match_response(response_text: str) -> dict[str, Any]:
    """解析 LLM 的匹配判断响应，多策略容错。"""
    text = response_text.strip()

    # 去掉 markdown 代码块
    text = re.sub(r"```(?:json)?\s*", "", text)

    # 尝试提取 JSON 对象
    result = None
    # 策略 1: 直接解析
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略 2: 提取 {} 块
    if result is None:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                result = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                # 策略 3: 去掉尾部逗号后重试
                cleaned = re.sub(r",\s*}", "}", text[start : end + 1])
                try:
                    result = json.loads(cleaned)
                except json.JSONDecodeError:
                    pass

    # 策略 4: 用正则从文本中提取 match/event_id
    if result is None:
        match_val = False
        event_id_val = None

        m_match = re.search(r'"?match"?\s*[:=]\s*(true|false)', text, re.IGNORECASE)
        if m_match:
            match_val = m_match.group(1).lower() == "true"

        m_eid = re.search(r'"?event_id"?\s*[:=]\s*(\d+)', text)
        if m_eid:
            event_id_val = int(m_eid.group(1))

        if m_match:
            logger.warning("正则提取匹配响应: match=%s, event_id=%s (原文: %s)", match_val, event_id_val, text[:100])
            return {"match": match_val, "event_id": event_id_val}

        logger.warning("无法解析 LLM 匹配响应: %s", text[:200])
        return {"match": False, "event_id": None}

    # 从解析出的 dict 中提取字段
    if not isinstance(result, dict):
        logger.warning("LLM 匹配响应不是对象: %s", type(result))
        return {"match": False, "event_id": None}

    raw_event_id = result.get("event_id")
    event_id: int | None = None
    if isinstance(raw_event_id, int) and not isinstance(raw_event_id, bool):
        event_id = raw_event_id
    elif isinstance(raw_event_id, str):
        raw_event_id = raw_event_id.strip()
        if raw_event_id:
            try:
                event_id = int(raw_event_id)
            except ValueError:
                event_id = None

    return {
        "match": bool(result.get("match", False)),
        "event_id": event_id,
    }
