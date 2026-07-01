"""
记忆2：历史素材创作记忆
ChromaDB 语义检索。每条文档 = 一次完整的素材方案。
"""

import hashlib
import uuid
from datetime import datetime
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from .schemas import CreativeRecord
from .embedding_fn import HashingEmbeddingFunction


class CreativeArchiveStore:
    """历史素材档案，基于 ChromaDB 语义检索"""

    COLLECTION_NAME = "creative_archive"

    def __init__(self, persist_path: str):
        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # HashingVectorizer: 纯 Python，零 DLL 依赖
        # TODO: 生产环境替换为中文语义模型
        #   推荐: DashScope Embedding API 或 shibing624/text2vec-base-chinese
        self.ef = HashingEmbeddingFunction(n_features=384)
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"description": "零食广告历史素材档案"},
            embedding_function=self.ef,
        )

    # ─── 写入 ─────────────────────────────────

    def archive(self, record: CreativeRecord) -> str:
        """存入一份素材方案。返回文档 ID"""
        if not record.id:
            record.id = self._generate_id(record.product_name)

        # 如果已存在则更新
        existing = self.collection.get(ids=[record.id])
        if existing and existing["ids"]:
            self.collection.update(
                ids=[record.id],
                documents=[record.to_embedding_text()],
                metadatas=[record.to_metadata()],
            )
        else:
            self.collection.add(
                ids=[record.id],
                documents=[record.to_embedding_text()],
                metadatas=[record.to_metadata()],
            )

        return record.id

    # ─── 检索 ─────────────────────────────────

    def search(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        script_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """语义检索相似历史素材"""
        where_filter = {}
        if category:
            where_filter["category"] = category
        if script_type:
            where_filter["script_type"] = script_type
        if user_id:
            where_filter["user_id"] = user_id

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter if where_filter else None,
        )

        return self._format_results(results)

    def search_by_product(self, product_name: str, n_results: int = 5) -> list[dict]:
        """按产品名检索"""
        return self.search(query=product_name, n_results=n_results)

    def search_by_category(self, category: str, query: str = "", n_results: int = 10) -> list[dict]:
        """按品类检索，可叠加语义查询"""
        q = query or category
        return self.search(query=q, category=category, n_results=n_results)

    def get_by_id(self, creative_id: str) -> Optional[dict]:
        """按 ID 精确获取"""
        result = self.collection.get(ids=[creative_id])
        if result and result["ids"]:
            return self._format_single(result, 0)
        return None

    # ─── 更新效果数据（第5层反馈层调用）─────────────────

    def update_performance(
        self,
        creative_id: str,
        total_cost: float,
        roi: float,
        avg_ctr: float,
        avg_completion_rate: float,
        performance_star: int,
    ):
        """反馈层回填效果数据到历史素材记录"""
        existing = self.collection.get(ids=[creative_id])
        if not existing or not existing["ids"]:
            return

        meta = existing["metadatas"][0]
        meta.update({
            "has_performance_data": True,
            "total_cost": total_cost,
            "roi": roi,
            "avg_ctr": avg_ctr,
            "avg_completion_rate": avg_completion_rate,
            "performance_star": performance_star,
        })

        self.collection.update(ids=[creative_id], metadatas=[meta])

    def count_by_strategy(self, category: str, script_type: str, hook_type: str) -> int:
        """统计某策略的素材数量"""
        result = self.collection.get(
            where={
                "$and": [
                    {"category": category},
                    {"script_type": script_type},
                    {"hook_type": hook_type},
                ]
            }
        )
        return len(result["ids"])

    def list_all(self, limit: int = 20, offset: int = 0) -> list[dict]:
        """分页列出所有素材（按创建时间倒序）"""
        result = self.collection.get(limit=limit, offset=offset)
        if not result or not result["ids"]:
            return []
        formatted = []
        for i, doc_id in enumerate(result["ids"]):
            item = self._format_single(result, i)
            if item:
                formatted.append(item)
        return formatted

    def get_categories(self) -> list[dict]:
        """获取所有类目及其素材数量"""
        result = self.collection.get()
        if not result or not result["ids"]:
            return []
        counts = {}
        for meta in result.get("metadatas", []):
            cat = meta.get("category", "未分类")
            counts[cat] = counts.get(cat, 0) + 1
        return [{"category": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]

    # ─── 工具方法 ─────────────────────────────────

    def _generate_id(self, product_name: str) -> str:
        h = hashlib.sha256(f"{product_name}{uuid.uuid4()}".encode()).hexdigest()[:12]
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"creative_{ts}_{h}"

    def _format_results(self, results: dict) -> list[dict]:
        """把 ChromaDB 返回格式化为统一结构"""
        formatted = []
        if not results or not results["ids"] or not results["ids"][0]:
            return formatted

        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for i, doc_id in enumerate(ids):
            item = {"id": doc_id, "similarity": round(1 - distances[i], 4) if distances else 1.0}
            if metadatas and i < len(metadatas):
                meta = metadatas[i]
                item.update({
                    "product_name": meta.get("product_name", ""),
                    "category": meta.get("category", ""),
                    "script_type": meta.get("script_type", ""),
                    "hook": meta.get("hook", ""),
                    "hook_type": meta.get("hook_type", ""),
                    "visual_style": meta.get("visual_style", ""),
                    "video_url": meta.get("video_url", ""),
                    "ad_titles": meta.get("ad_titles", ""),
                    "suggested_audience": meta.get("suggested_audience", ""),
                    "bundle_json": meta.get("bundle_json", ""),
                    "has_performance_data": meta.get("has_performance_data", False),
                    "roi": meta.get("roi", 0),
                    "performance_star": meta.get("performance_star", 0),
                    "avg_ctr": meta.get("avg_ctr", 0),
                    "total_cost": meta.get("total_cost", 0),
                    "created_at": meta.get("created_at", ""),
                })
            formatted.append(item)

        return formatted

    def _format_single(self, result: dict, idx: int) -> Optional[dict]:
        if not result["ids"] or idx >= len(result["ids"]):
            return None
        meta = result["metadatas"][idx] if result.get("metadatas") else {}
        return {"id": result["ids"][idx], **meta}
