"""
素材↔广告 手动关联

投手在千川后台用素材创建广告后，回到系统关联 素材ID ↔ 广告ID。
关联后第3天起，Celery Beat 自动拉取该广告的效果数据（持续到第30天）。

存储: SQLite 表 creative_ad_links
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from .schemas import CreativeAdLink


class CreativeAdLinker:
    """素材↔千川广告 手动关联管理"""

    TABLE = "creative_ad_links"

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
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creative_id TEXT NOT NULL,
                    ad_id TEXT NOT NULL,
                    advertiser_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    UNIQUE(creative_id, ad_id)
                )
            """)

    # ─── 关联操作 ─────────────────────────────────

    def link(self, user_id: str, creative_id: str, ad_id: str, advertiser_id: str) -> CreativeAdLink:
        """创建素材→广告关联"""
        link = CreativeAdLink(
            creative_id=creative_id,
            ad_id=ad_id,
            advertiser_id=advertiser_id,
            user_id=user_id,
        )
        with self._connect() as conn:
            conn.execute(
                f"""INSERT OR IGNORE INTO {self.TABLE}
                    (creative_id, ad_id, advertiser_id, user_id, linked_at)
                    VALUES (?,?,?,?,?)""",
                (link.creative_id, link.ad_id, link.advertiser_id, link.user_id, link.linked_at)
            )
        return link

    def bulk_link(self, user_id: str, links: list[dict]) -> int:
        """批量关联 [{creative_id, ad_id, advertiser_id}] → 返回成功数"""
        count = 0
        for l in links:
            try:
                self.link(user_id, l["creative_id"], l["ad_id"], l["advertiser_id"])
                count += 1
            except Exception:
                pass
        return count

    def unlink(self, creative_id: str, ad_id: str):
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM {self.TABLE} WHERE creative_id=? AND ad_id=?",
                (creative_id, ad_id)
            )

    # ─── 查询 ─────────────────────────────────────

    def get_by_creative(self, creative_id: str) -> list[dict]:
        """查某个素材关联了哪些广告"""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.TABLE} WHERE creative_id=?",
                (creative_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_ad(self, ad_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {self.TABLE} WHERE ad_id=?",
                (ad_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_unlinked_creatives(self, user_id: str, days: int = 7) -> list[str]:
        """查用户最近 N 天内生成但尚未关联的素材"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT c.id as creative_id, c.product_name
                    FROM {self.TABLE} l
                    RIGHT JOIN creative_archive c ON l.creative_id = c.id
                    ...  -- 此处需要跨存储查询，见下方说明
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_active_links(self, user_id: Optional[str] = None) -> list[dict]:
        """
        获取需要拉取效果数据的关联。
        条件: 关联后 ≥ 3天 且 ≤ 30天
        """
        today = datetime.now().date().isoformat()
        with self._connect() as conn:
            query = f"""
                SELECT * FROM {self.TABLE}
                WHERE date(linked_at) <= date(?, '-3 days')
                  AND date(linked_at) >= date(?, '-30 days')
            """
            params = [today, today]

            if user_id:
                query += " AND user_id=?"
                params.append(user_id)

            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def list_by_user(self, user_id: str) -> list[dict]:
        """查看用户所有关联"""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.TABLE} WHERE user_id=? ORDER BY linked_at DESC",
                (user_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_active(self) -> int:
        """活跃关联数（需要拉取数据的）"""
        return len(self.get_active_links())
