"""
一进：TaskContextForEnv — 聚合所有上下文

从 Memory 1/2/3/4 + 产品输入 + 技能注册表 聚合为统一的上下文对象。
这是整个上下文注入系统的唯一入口。
"""

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SkillDef:
    """技能定义"""
    name: str
    description: str
    content: str = ""          # SKILL.md 内容


@dataclass
class ProjectResource:
    """项目资源"""
    id: str = ""
    resource_type: str = ""    # github_repo | local_dir | brand_asset
    resource_ref: dict = field(default_factory=dict)
    label: str = ""


@dataclass
class TaskContextForEnv:
    """
    聚合所有上下文 — "一进"

    从四个记忆层 + 外部输入聚合为统一上下文对象。
    然后通过 write_context_files() 和 inject_runtime_config() 分别输出。
    """

    # ── Layer 1: 会话连续性 ──
    session_id: str = ""
    prior_session_id: str = ""
    prior_work_dir: str = ""
    prior_product_id: str = ""

    # ── Layer 2: 技能 ──
    available_skills: list[SkillDef] = field(default_factory=list)

    # ── Layer 3: 项目资源 ──
    product_name: str = ""
    category_l1: str = ""
    category_l2: str = ""
    product_info: dict = field(default_factory=dict)
    brand_assets: dict = field(default_factory=dict)
    project_resources: list[ProjectResource] = field(default_factory=list)

    # ── Memory 1: 用户偏好 ──
    user_id: str = ""
    user_preferences: dict[str, str] = field(default_factory=dict)
    preferred_hook: str = ""
    preferred_visual: str = ""
    taboo_words: list[str] = field(default_factory=list)
    disliked_items: list[str] = field(default_factory=list)

    # ── Memory 2: 历史素材 ──
    historical_creatives: list[dict] = field(default_factory=list)

    # ── Memory 3: 会话微调 ──
    session_feedback: list[dict] = field(default_factory=list)
    feedback_summary: str = ""

    # ── Memory 4: 策略效果 ──
    strategy_effects: list[dict] = field(default_factory=list)
    strategy_insight: str = ""
    top_category_strategies: list[dict] = field(default_factory=list)

    # ── 元信息 ──
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def aggregate(
        cls,
        *,
        memory_manager,
        product_input: dict,
        session_id: str = "",
        user_id: str = "",
        skills: Optional[list[SkillDef]] = None,
        prior_session_id: str = "",
        prior_work_dir: str = "",
    ) -> "TaskContextForEnv":
        """
        从所有数据源聚合上下文 — 唯一入口。

        Args:
            memory_manager: MemoryManager 实例
            product_input: 用户提交的产品信息
            session_id: 当前会话 ID
            user_id: 用户 ID
            skills: 可用技能列表
            prior_session_id: 上次会话 ID（恢复用）
            prior_work_dir: 上次工作目录（恢复用）
        """
        ctx = cls(
            session_id=session_id or uuid.uuid4().hex[:8],
            prior_session_id=prior_session_id,
            prior_work_dir=prior_work_dir,
            user_id=user_id,
            available_skills=skills or [],
            product_info=product_input,
        )

        # 从 product_input 提取字段
        ctx.product_name = product_input.get("product_name", "")
        ctx.category_l1 = product_input.get("category_l1", "")
        ctx.category_l2 = product_input.get("features", {}).get(
            "category_l2", product_input.get("category_l2", "")
        )

        # ── 聚合 Memory 1: 用户偏好 ──
        if user_id and memory_manager:
            ctx.user_preferences = memory_manager.get_user_preferences(user_id)
            ctx.taboo_words = memory_manager.get_disliked(user_id)
            ctx.preferred_hook = ctx.user_preferences.get("preferred_hook", "")
            ctx.preferred_visual = ctx.user_preferences.get("preferred_visual", "")

        # ── 聚合 Memory 2: 历史素材 ──
        if memory_manager:
            search_query = cls._build_search_query(product_input)
            ctx.historical_creatives = memory_manager.search_creatives(
                query=search_query,
                category=ctx.category_l2,
                n_results=5,
            )

        # ── 聚合 Memory 3: 会话微调 ──
        if session_id and memory_manager:
            fb_history = memory_manager.get_session_history(session_id)
            ctx.session_feedback = [
                {
                    "round": fb.round_number,
                    "feedback": fb.user_feedback,
                    "adjusted_field": fb.adjusted_field,
                    "adjusted_to": fb.adjusted_to,
                }
                for fb in fb_history
            ]
            ctx.feedback_summary = memory_manager.get_feedback_for_prompt(session_id)

        # ── 聚合 Memory 4: 策略效果 ──
        if memory_manager and ctx.category_l2:
            ctx.strategy_insight = memory_manager.get_strategy_insight(ctx.category_l2)
            ctx.top_category_strategies = memory_manager.get_strategy_comparison(
                ctx.category_l2
            )

        return ctx

    @staticmethod
    def _build_search_query(product: dict) -> str:
        """构建检索查询文本"""
        parts = [
            product.get("category_l2", ""),
            product.get("category_l1", ""),
            product.get("product_name", ""),
        ]
        features = product.get("features", {})
        if features.get("taste_tags"):
            parts.extend(features["taste_tags"])
        if features.get("selling_points"):
            parts.extend(features["selling_points"][:2])
        return " ".join(filter(None, parts))

    def to_dict(self) -> dict:
        """转为字典（用于 JSON 序列化）"""
        return {
            "session_id": self.session_id,
            "prior_session_id": self.prior_session_id,
            "prior_work_dir": self.prior_work_dir,
            "user_id": self.user_id,
            "product_name": self.product_name,
            "category_l1": self.category_l1,
            "category_l2": self.category_l2,
            "user_preferences": self.user_preferences,
            "taboo_words": self.taboo_words,
            "historical_creatives_count": len(self.historical_creatives),
            "strategy_insight": self.strategy_insight,
            "feedback_rounds": len(self.session_feedback),
            "available_skills": [s.name for s in self.available_skills],
            "created_at": self.created_at,
        }
