"""
记忆管理器 — 统一门面
Agent 通过这一个入口访问全部四种记忆，不需要知道底层是 SQLite 还是 ChromaDB。

使用方式：
    mgr = MemoryManager(sqlite_path="./data/snack_agent.db", chroma_path="./data/chroma")
    mgr.start_session(session_id)

    # Agent 调用
    prefs = mgr.get_user_preferences(user_id)
    similar = mgr.search_creatives("膨化食品 薯条 麻辣")
    mgr.record_feedback(session_id, feedback_text, ...)

    mgr.end_session(session_id, user_id)
"""

import uuid
from datetime import datetime
from typing import Optional

from .user_preferences import UserPreferenceStore
from .creative_archive import CreativeArchiveStore
from .session_feedback import SessionFeedbackStore
from .strategy_effects import StrategyEffectStore
from .schemas import (
    UserPreference,
    CreativeRecord,
    SessionFeedback,
    StrategyEffect,
    SearchResult,
)


class MemoryManager:
    """四维记忆的统一入口"""

    def __init__(self, sqlite_path: str, chroma_path: str):
        self.prefs = UserPreferenceStore(sqlite_path)
        self.creatives = CreativeArchiveStore(chroma_path)
        self.feedback = SessionFeedbackStore(self.prefs)
        self.effects = StrategyEffectStore(sqlite_path, chroma_path)

    # ═══════════════════════════════════════════
    # 记忆1：用户偏好
    # ═══════════════════════════════════════════

    def get_user_preferences(self, user_id: str) -> dict[str, str]:
        """获取用户偏好 → {key: value}"""
        return self.prefs.get_all(user_id)

    def get_user_preferences_detailed(self, user_id: str) -> list[dict]:
        """获取含置信度的完整偏好列表"""
        return self.prefs.get_all_with_confidence(user_id)

    def set_user_preference(self, user_id: str, key: str, value: str):
        """用户明确设定偏好"""
        self.prefs.set_explicit(user_id, key, value)

    def get_disliked(self, user_id: str) -> list[str]:
        """获取用户不喜欢的项目"""
        return self.prefs.get_disliked(user_id)

    def format_preferences_for_prompt(self, user_id: str) -> str:
        """将用户偏好格式化为注入 LLM prompt 的文本"""
        prefs = self.get_user_preferences(user_id)
        if not prefs:
            return ""

        lines = ["\n用户偏好参考："]
        mapping = {
            "brand_tone": "品牌调性",
            "preferred_hook": "偏好创意类型",
            "disliked_hook": "避免的创意类型",
            "preferred_duration": "偏好时长",
            "preferred_visual": "偏好视觉风格",
            "taboo_words": "禁忌词",
        }
        for key, label in mapping.items():
            if key in prefs:
                lines.append(f"  - {label}: {prefs[key]}")

        # 处理 disliked 系列
        disliked = self.get_disliked(user_id)
        if disliked:
            lines.append(f"  - 用户明确不喜欢: {', '.join(disliked)}")

        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # 记忆2：历史素材
    # ═══════════════════════════════════════════

    def archive_creative(self, record: CreativeRecord) -> str:
        """存入素材方案"""
        return self.creatives.archive(record)

    def search_creatives(
        self,
        query: str,
        n_results: int = 5,
        category: Optional[str] = None,
        script_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """语义检索历史素材"""
        return self.creatives.search(
            query=query,
            n_results=n_results,
            category=category,
            script_type=script_type,
            user_id=user_id,
        )

    def get_creative_by_id(self, creative_id: str) -> Optional[dict]:
        return self.creatives.get_by_id(creative_id)

    # ═══════════════════════════════════════════
    # 记忆3：会话微调
    # ═══════════════════════════════════════════

    def start_session(self, session_id: str = "") -> str:
        """开始新会话，返回 session_id"""
        sid = session_id or str(uuid.uuid4())[:8]
        self.feedback.start_session(sid)
        return sid

    def record_feedback(
        self,
        session_id: str,
        user_feedback: str,
        adjustment_type: str,
        adjusted_field: str,
        adjusted_from: str,
        adjusted_to: str,
    ):
        """记录一条交互微调"""
        self.feedback.record(
            session_id, user_feedback, adjustment_type,
            adjusted_field, adjusted_from, adjusted_to,
        )

    def get_session_history(self, session_id: str) -> list[SessionFeedback]:
        return self.feedback.get_history(session_id)

    def get_feedback_for_prompt(self, session_id: str) -> str:
        """获取格式化的微调历史，用于注入 LLM prompt"""
        return self.feedback.format_for_prompt(session_id)

    def end_session(self, session_id: str, user_id: str) -> list[str]:
        """结束会话，自动升级高频微调到用户偏好"""
        return self.feedback.end_session(session_id, user_id)

    # ═══════════════════════════════════════════
    # 记忆4：策略效果
    # ═══════════════════════════════════════════

    def record_strategy_effect(self, effect: StrategyEffect) -> int:
        """记录策略效果"""
        return self.effects.record(effect)

    def get_strategy_aggregate(
        self,
        category: Optional[str] = None,
        script_type: Optional[str] = None,
        hook_type: Optional[str] = None,
    ) -> dict:
        """策略效果聚合查询"""
        return self.effects.aggregate_by_strategy(category, script_type, hook_type)

    def get_top_performers(self, user_id: Optional[str] = None, category: Optional[str] = None) -> list[dict]:
        """Top 效果素材"""
        return self.effects.top_performers(user_id=user_id, category=category)

    def get_strategy_comparison(self, category: str) -> list[dict]:
        """同品类策略对比"""
        return self.effects.strategy_comparison(category)

    def get_strategy_insight(self, category: str) -> str:
        """策略效果自然语言洞察"""
        return self.effects.generate_insight(category)

    # ═══════════════════════════════════════════
    # 综合检索（Agent search_kb 工具的核心逻辑）
    # ═══════════════════════════════════════════

    def search_kb(self, query: str, category: Optional[str] = None) -> SearchResult:
        """
        Agent 唯一的搜索入口。
        同时检索记忆2（历史素材）和记忆4（策略效果），返回统一结果。
        """
        similar = self.search_creatives(query=query, category=category, n_results=5)
        strategies = self.effects.search_similar_strategies(query, n_results=5)

        insight = ""
        if category:
            insight = self.effects.generate_insight(category)

        return SearchResult(
            similar_creatives=similar,
            strategy_effects=strategies,
            insight=insight,
        )


# ═══════════════════════════════════════════════
# 便捷工厂函数
# ═══════════════════════════════════════════════

def create_memory_manager(sqlite_path: str = "./data/snack_agent.db", chroma_path: str = "./data/chroma") -> MemoryManager:
    """工厂函数：一键创建 MemoryManager"""
    return MemoryManager(sqlite_path=sqlite_path, chroma_path=chroma_path)
