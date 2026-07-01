"""
记忆1：用户个人偏好记忆
SQLite 存储，跨会话持久。记录品牌调性、风格偏好、禁忌规则等。
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional

from .schemas import UserPreference


class UserPreferenceStore:
    """用户偏好 CRUD，底层 SQLite"""

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    preference_key TEXT NOT NULL,
                    preference_value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    source TEXT DEFAULT 'agent_inferred',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, preference_key)
                )
            """)

    # ─── 写入 ─────────────────────────────────

    def upsert(self, pref: UserPreference):
        """插入或更新偏好。已存在 → 更新 + 提升置信度"""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, confidence FROM user_preferences WHERE user_id=? AND preference_key=?",
                (pref.user_id, pref.preference_key)
            ).fetchone()

            if existing:
                new_confidence = min(1.0, max(existing["confidence"], pref.confidence))
                conn.execute(
                    """UPDATE user_preferences
                       SET preference_value=?, confidence=?, source=?, updated_at=?
                       WHERE user_id=? AND preference_key=?""",
                    (pref.preference_value, new_confidence, pref.source,
                     datetime.now().isoformat(), pref.user_id, pref.preference_key)
                )
            else:
                conn.execute(
                    """INSERT INTO user_preferences
                       (user_id, preference_key, preference_value, confidence, source, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (pref.user_id, pref.preference_key, pref.preference_value,
                     pref.confidence, pref.source, pref.created_at, pref.updated_at)
                )

    def set_explicit(self, user_id: str, key: str, value: str):
        """用户明确设定的偏好（置信度直接=1.0）"""
        self.upsert(UserPreference(
            user_id=user_id, preference_key=key, preference_value=value,
            confidence=1.0, source="user_set"
        ))

    def boost_confidence(self, user_id: str, key: str, delta: float = 0.1):
        """确认一次 +0.1 置信度"""
        with self._connect() as conn:
            conn.execute(
                """UPDATE user_preferences
                   SET confidence = MIN(1.0, confidence + ?), updated_at = ?
                   WHERE user_id = ? AND preference_key = ?""",
                (delta, datetime.now().isoformat(), user_id, key)
            )

    # ─── 读取 ─────────────────────────────────

    def get(self, user_id: str, key: str) -> Optional[str]:
        """获取单个偏好值"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT preference_value FROM user_preferences WHERE user_id=? AND preference_key=?",
                (user_id, key)
            ).fetchone()
        return row["preference_value"] if row else None

    def get_all(self, user_id: str) -> dict[str, str]:
        """获取某用户所有偏好 → {key: value}"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT preference_key, preference_value FROM user_preferences WHERE user_id=?",
                (user_id,)
            ).fetchall()
        return {r["preference_key"]: r["preference_value"] for r in rows}

    def get_all_with_confidence(self, user_id: str) -> list[dict]:
        """获取全部偏好（含置信度），高置信度优先"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT preference_key, preference_value, confidence, source
                   FROM user_preferences WHERE user_id=?
                   ORDER BY confidence DESC""",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_disliked(self, user_id: str) -> list[str]:
        """获取所有被标记为 disliked 的值"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT preference_value FROM user_preferences WHERE user_id=? AND preference_key LIKE 'disliked_%'",
                (user_id,)
            ).fetchall()
        return [r["preference_value"] for r in rows]

    # ─── 删除 ─────────────────────────────────

    def delete(self, user_id: str, key: str):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM user_preferences WHERE user_id=? AND preference_key=?",
                (user_id, key)
            )

    def mark_disliked(self, user_id: str, item: str, context: str = ""):
        """记录用户不喜欢的某个方向/词汇/风格"""
        self.upsert(UserPreference(
            user_id=user_id,
            preference_key=f"disliked_{context}" if context else "disliked_general",
            preference_value=item,
            confidence=0.6,
            source="agent_inferred"
        ))

    def upsert_from_session(self, user_id: str, key: str, value: str):
        """会话微调升级为偏好（置信度 0.6，来源标记为 agent_inferred）"""
        self.upsert(UserPreference(
            user_id=user_id,
            preference_key=key,
            preference_value=value,
            confidence=0.6,
            source="agent_inferred"
        ))
