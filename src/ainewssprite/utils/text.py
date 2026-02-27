"""文本清洗工具"""

from __future__ import annotations

import hashlib
import html
import re


def compute_content_hash(title: str, url: str) -> str:
    """计算内容指纹: SHA256(title + url)"""
    raw = f"{title.strip().lower()}|{url.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean_html(text: str) -> str:
    """去除 HTML 标签，解码 HTML 实体。"""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate(text: str, max_length: int = 500) -> str:
    """截断文本到指定长度。"""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
