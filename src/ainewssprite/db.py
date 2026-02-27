"""SQLite 数据库层"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

from ainewssprite.models import RawNewsItem


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title_zh     TEXT NOT NULL,
    summary_zh   TEXT NOT NULL,
    category     TEXT NOT NULL,
    tags         TEXT DEFAULT '[]',
    importance   INTEGER DEFAULT 3,
    first_seen   TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    source_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     INTEGER REFERENCES events(id),
    title        TEXT NOT NULL,
    url          TEXT NOT NULL UNIQUE,
    source       TEXT NOT NULL,
    author       TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    published_at TEXT,
    content_hash TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_event_id ON articles(event_id);
CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
CREATE INDEX IF NOT EXISTS idx_events_first_seen ON events(first_seen);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    title_zh, summary_zh, tags, content='events', content_rowid='id'
);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, title_zh, summary_zh, tags)
    VALUES (new.id, new.title_zh, new.summary_zh, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title_zh, summary_zh, tags)
    VALUES ('delete', old.id, old.title_zh, old.summary_zh, old.tags);
    INSERT INTO events_fts(rowid, title_zh, summary_zh, tags)
    VALUES (new.id, new.title_zh, new.summary_zh, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title_zh, summary_zh, tags)
    VALUES ('delete', old.id, old.title_zh, old.summary_zh, old.tags);
END;
"""


class NewsDB:
    """SQLite 数据库操作封装。"""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "NewsDB":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("数据库未连接，请先调用 connect() 或使用 with 语句")
        return self._conn

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.executescript(_FTS_SCHEMA)
        self.conn.executescript(_FTS_TRIGGERS)

    def url_exists(self, url: str) -> bool:
        """检查 URL 是否已存在。"""
        row = self.conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
        return row is not None

    def filter_new_items(self, items: Sequence[RawNewsItem]) -> list[RawNewsItem]:
        """过滤掉已存在的条目，返回新条目列表。"""
        return [item for item in items if not self.url_exists(item.url)]

    def insert_event(
        self,
        title_zh: str,
        summary_zh: str,
        category: str,
        tags: list[str],
        importance: int,
        now: str,
    ) -> int:
        """插入新事件，返回事件 ID。"""
        cursor = self.conn.execute(
            """INSERT INTO events (title_zh, summary_zh, category, tags, importance,
               first_seen, last_updated, source_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (title_zh, summary_zh, category, json.dumps(tags, ensure_ascii=False), importance, now, now),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def update_event(
        self,
        event_id: int,
        summary_zh: str,
        now: str,
        tags: list[str] | None = None,
        importance: int | None = None,
    ) -> None:
        """更新已有事件的摘要和元信息。"""
        self.conn.execute(
            """UPDATE events SET summary_zh = ?, last_updated = ?,
               source_count = source_count + 1
               WHERE id = ?""",
            (summary_zh, now, event_id),
        )
        if tags is not None:
            self.conn.execute(
                "UPDATE events SET tags = ? WHERE id = ?",
                (json.dumps(tags, ensure_ascii=False), event_id),
            )
        if importance is not None:
            self.conn.execute(
                "UPDATE events SET importance = ? WHERE id = ?",
                (importance, event_id),
            )
        self.conn.commit()

    def insert_article(self, item: RawNewsItem, event_id: int, now: str) -> int:
        """插入原始文章记录，返回文章 ID。"""
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO articles
               (event_id, title, url, source, author, description, published_at, content_hash, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                item.title,
                item.url,
                item.source,
                item.author,
                item.description,
                item.published_at.isoformat() if item.published_at else None,
                item.content_hash,
                now,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_recent_events(self, days: int) -> list[dict[str, Any]]:
        """获取最近 N 天的事件列表。"""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT id, title_zh, summary_zh, category, tags, importance,
                      first_seen, last_updated, source_count
               FROM events WHERE first_seen >= ? ORDER BY first_seen DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_date(self, date_str: str) -> list[dict[str, Any]]:
        """获取指定日期的事件列表（按 first_seen 的日期部分匹配）。"""
        rows = self.conn.execute(
            """SELECT id, title_zh, summary_zh, category, tags, importance,
                      first_seen, last_updated, source_count
               FROM events WHERE date(first_seen) = ? OR date(last_updated) = ?
               ORDER BY importance DESC, first_seen DESC""",
            (date_str, date_str),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_ids(self, event_ids: set[int]) -> list[dict[str, Any]]:
        """获取指定 ID 的事件列表。"""
        if not event_ids:
            return []
        placeholders = ",".join("?" for _ in event_ids)
        rows = self.conn.execute(
            f"""SELECT id, title_zh, summary_zh, category, tags, importance,
                       first_seen, last_updated, source_count
                FROM events WHERE id IN ({placeholders})
                ORDER BY importance DESC, first_seen DESC""",
            list(event_ids),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_articles_for_event(self, event_id: int) -> list[dict[str, Any]]:
        """获取事件关联的所有文章。"""
        rows = self.conn.execute(
            """SELECT id, title, url, source, author, description, published_at, fetched_at
               FROM articles WHERE event_id = ? ORDER BY fetched_at""",
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_events(self, query: str) -> list[dict[str, Any]]:
        """全文搜索事件。"""
        rows = self.conn.execute(
            """SELECT e.id, e.title_zh, e.summary_zh, e.category, e.tags,
                      e.importance, e.first_seen, e.last_updated, e.source_count
               FROM events_fts fts
               JOIN events e ON fts.rowid = e.id
               WHERE events_fts MATCH ?
               ORDER BY e.first_seen DESC""",
            (query,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self, date_str: str | None = None) -> dict[str, Any]:
        """获取统计信息。"""
        if date_str:
            event_count = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE date(first_seen) = ? OR date(last_updated) = ?",
                (date_str, date_str),
            ).fetchone()[0]
            article_count = self.conn.execute(
                "SELECT COUNT(*) FROM articles WHERE date(fetched_at) = ?",
                (date_str,),
            ).fetchone()[0]
            source_rows = self.conn.execute(
                """SELECT source, COUNT(*) as cnt FROM articles
                   WHERE date(fetched_at) = ? GROUP BY source""",
                (date_str,),
            ).fetchall()
        else:
            event_count = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            article_count = self.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            source_rows = self.conn.execute(
                "SELECT source, COUNT(*) as cnt FROM articles GROUP BY source"
            ).fetchall()
        return {
            "event_count": event_count,
            "article_count": article_count,
            "sources": {r["source"]: r["cnt"] for r in source_rows},
        }
