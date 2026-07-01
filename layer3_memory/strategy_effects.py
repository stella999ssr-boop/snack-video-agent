"""
记忆4：策略效果联动记忆
关联"创意策略"和"投放效果"，驱动数据化素材决策。

双存储：
  - SQLite: 结构化条件查询（按品类+策略类型聚合统计）
  - ChromaDB: 语义检索（发现相似策略的效果规律）
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from .schemas import StrategyEffect
from .embedding_fn import HashingEmbeddingFunction


class StrategyEffectStore:
    """策略效果联动 — SQLite 主存储 + ChromaDB 语义检索"""

    COLLECTION_NAME = "strategy_effects"
    SQL_TABLE = "strategy_effects"

    def __init__(self, sqlite_path: str, chroma_path: str):
        # SQLite
        os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
        self.sqlite_path = sqlite_path
        self._init_sqlite()

        # ChromaDB
        self.chroma_client = chromadb.PersistentClient(
            path=chroma_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.ef = HashingEmbeddingFunction(n_features=384)
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "策略效果联动数据"},
            embedding_function=self.ef,
        )

    def _connect_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self):
        with self._connect_sqlite() as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.SQL_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creative_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,

                    category TEXT,
                    script_type TEXT,
                    hook_type TEXT,
                    visual_style TEXT,
                    duration INTEGER,

                    target_gender TEXT,
                    target_age TEXT,
                    target_interests TEXT,

                    ctr REAL,
                    cvr REAL,
                    completion_rate REAL,
                    roi REAL,
                    convert_cost REAL,
                    impressions INTEGER,
                    stat_cost REAL,
                    pay_order_count INTEGER,
                    pay_order_amount REAL,

                    user_rating INTEGER,
                    feedback_text TEXT,
                    recorded_at TEXT NOT NULL
                )
            """)

    # ─── 写入 ─────────────────────────────────

    def record(self, effect: StrategyEffect) -> int:
        """记录一条效果数据（双写）"""
        # 1. SQLite
        with self._connect_sqlite() as conn:
            cursor = conn.execute(
                f"""INSERT INTO {self.SQL_TABLE}
                    (creative_id, user_id, category, script_type, hook_type,
                     visual_style, duration, target_gender, target_age, target_interests,
                     ctr, cvr, completion_rate, roi, convert_cost, impressions,
                     stat_cost, pay_order_count, pay_order_amount,
                     user_rating, feedback_text, recorded_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    effect.creative_id, effect.user_id,
                    effect.category, effect.script_type, effect.hook_type,
                    effect.visual_style, effect.duration,
                    effect.target_gender, effect.target_age, effect.target_interests,
                    effect.ctr, effect.cvr, effect.completion_rate,
                    effect.roi, effect.convert_cost, effect.impressions,
                    effect.stat_cost, effect.pay_order_count, effect.pay_order_amount,
                    effect.user_rating, effect.feedback_text, effect.recorded_at,
                )
            )
            row_id = cursor.lastrowid

        # 2. ChromaDB（语义检索用）
        doc_id = f"effect_{effect.creative_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.collection.add(
            ids=[doc_id],
            documents=[effect.to_embedding_text()],
            metadatas=[{
                "creative_id": effect.creative_id,
                "category": effect.category,
                "script_type": effect.script_type,
                "hook_type": effect.hook_type,
                "ctr": effect.ctr,
                "roi": effect.roi,
                "completion_rate": effect.completion_rate,
                "recorded_at": effect.recorded_at,
            }],
        )

        return row_id

    # ─── 结构化查询（SQLite）──────────────────

    def aggregate_by_strategy(
        self,
        category: Optional[str] = None,
        script_type: Optional[str] = None,
        hook_type: Optional[str] = None,
    ) -> dict:
        """按策略维度聚合效果数据"""
        conditions = []
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if script_type:
            conditions.append("script_type = ?")
            params.append(script_type)
        if hook_type:
            conditions.append("hook_type = ?")
            params.append(hook_type)

        where = " AND ".join(conditions) if conditions else "1=1"

        with self._connect_sqlite() as conn:
            row = conn.execute(
                f"""SELECT
                      COUNT(*) as sample_count,
                      AVG(ctr) as avg_ctr,
                      AVG(cvr) as avg_cvr,
                      AVG(completion_rate) as avg_completion,
                      AVG(roi) as avg_roi,
                      AVG(convert_cost) as avg_convert_cost,
                      MAX(roi) as max_roi,
                      SUM(pay_order_count) as total_orders
                    FROM {self.SQL_TABLE}
                    WHERE {where}""",
                params
            ).fetchone()

        return dict(row) if row else {}

    def top_performers(
        self,
        user_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict]:
        """返回效果最好的素材"""
        conditions = ["roi > 0"]
        params = []

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if category:
            conditions.append("category = ?")
            params.append(category)

        where = " AND ".join(conditions)

        with self._connect_sqlite() as conn:
            rows = conn.execute(
                f"""SELECT creative_id, category, script_type, hook_type,
                           ctr, cvr, roi, completion_rate, impressions, pay_order_count
                    FROM {self.SQL_TABLE}
                    WHERE {where}
                    ORDER BY roi DESC
                    LIMIT ?""",
                params + [limit]
            ).fetchall()

        return [dict(r) for r in rows]

    def strategy_comparison(self, category: str) -> list[dict]:
        """同一品类下，不同策略的效果对比（Agent 选策略时用）"""
        with self._connect_sqlite() as conn:
            rows = conn.execute(
                f"""SELECT
                      script_type,
                      hook_type,
                      COUNT(*) as sample_count,
                      AVG(ctr) as avg_ctr,
                      AVG(cvr) as avg_cvr,
                      AVG(completion_rate) as avg_completion,
                      AVG(roi) as avg_roi,
                      AVG(convert_cost) as avg_convert_cost
                    FROM {self.SQL_TABLE}
                    WHERE category = ? AND roi > 0
                    GROUP BY script_type, hook_type
                    ORDER BY avg_roi DESC""",
                [category]
            ).fetchall()

        return [dict(r) for r in rows]

    def generate_insight(self, category: str) -> str:
        """基于策略效果数据生成自然语言洞察"""
        comparison = self.strategy_comparison(category)
        if not comparison:
            return f"暂无 {category} 品类的效果数据，建议参考创意模式而非效果数据。"

        best = comparison[0]
        insights = []

        # 最高 ROI 策略
        insights.append(
            f"{best['script_type']}+{best['hook_type']} 组合 ROI 最高 "
            f"({best['avg_roi']:.1f})，{best['sample_count']} 个样本"
        )

        # CTR vs CVR 权衡
        if len(comparison) >= 2:
            second = comparison[1]
            if best["avg_ctr"] < second["avg_ctr"]:
                insights.append(
                    f"注意：{second['script_type']}+{second['hook_type']} "
                    f"CTR 更高 ({second['avg_ctr']:.1%} vs {best['avg_ctr']:.1%})，"
                    f"但 ROI 更低 ({second['avg_roi']:.1f} vs {best['avg_roi']:.1f})"
                )

        return "。".join(insights) + "。"

    # ─── 语义检索（ChromaDB）──────────────────

    def search_similar_strategies(self, query: str, n_results: int = 5) -> list[dict]:
        """语义搜索相似策略效果"""
        results = self.collection.query(query_texts=[query], n_results=n_results)

        formatted = []
        if not results["ids"] or not results["ids"][0]:
            return formatted

        for i, doc_id in enumerate(results["ids"][0]):
            distance = results.get("distances", [[]])[0]
            meta = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
            item = {
                "id": doc_id,
                "similarity": round(1 - distance[i], 4) if distance else 1.0,
            }
            if meta and i < len(meta):
                item.update(meta[i])
            formatted.append(item)

        return formatted
