"""YAML 配置加载"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: str | Path) -> dict[str, Any]:
    """加载 YAML 配置文件，返回配置字典。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError(f"配置文件格式错误: {path}")
    return config


def get_enabled_rss_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    """返回所有启用的 RSS 源配置。"""
    return [s for s in config.get("rss_sources", []) if s.get("enabled", True)]


def get_hackernews_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """返回 HN 配置，如果禁用则返回 None。"""
    hn = config.get("hackernews", {})
    if not hn.get("enabled", True):
        return None
    return hn


def get_db_path(config: dict[str, Any]) -> Path:
    """返回 SQLite 数据库路径。"""
    return Path(config.get("general", {}).get("db_path", "data/news.db"))


def get_output_dir(config: dict[str, Any]) -> Path:
    """返回输出目录路径。"""
    return Path(config.get("general", {}).get("output_dir", "data/output"))


def get_merge_window_days(config: dict[str, Any]) -> int:
    """返回相似合并的回溯天数。"""
    return config.get("processing", {}).get("merge_window_days", 7)


def get_timezone(config: dict[str, Any]) -> str:
    """返回时区配置。"""
    return config.get("general", {}).get("timezone", "Asia/Shanghai")


def get_http_config(config: dict[str, Any]) -> dict[str, Any]:
    """返回 HTTP 客户端配置。"""
    defaults = {"timeout": 30, "delay": 1.0, "max_retries": 3, "user_agent": "ainewssprite/1.0"}
    http_cfg = config.get("http", {})
    return {**defaults, **http_cfg}


def get_llm_config(config: dict[str, Any]) -> dict[str, Any]:
    """返回 LLM 配置。"""
    defaults = {
        "api_key": "",
        "base_url": "",
        "model": "gpt-4o",
        "batch_size": 8,
        "temperature": 0.3,
    }
    llm_cfg = config.get("llm", {})
    return {**defaults, **llm_cfg}


def get_categories(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """返回分类配置。"""
    return config.get("categories", {})
