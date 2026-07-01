"""
第3层 · 记忆层 — 统一数据模型
"""

from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════
# 记忆1：用户偏好
# ═══════════════════════════════════════════════════

@dataclass
class UserPreference:
    user_id: str
    preference_key: str
    preference_value: str
    confidence: float = 0.5
    source: str = "agent_inferred"  # "user_set" | "agent_inferred"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════
# 记忆2：历史素材
# ═══════════════════════════════════════════════════

@dataclass
class CreativeRecord:
    """写入 ChromaDB 的历史素材记录"""
    product_name: str
    category: str                        # 品类
    script_type: str                     # 创意类型（对比测评/知识科普/场景植入等）
    hook: str                            # 钩子文案
    hook_type: str                       # 钩子类型（价格反差/痛点刺激/好奇心等）
    visual_style: str                    # 视觉风格描述
    wan22_prompt: str                    # 生成视频用的 Prompt
    id: str = ""                         # creative_<timestamp>_<hash>（存档时自动生成）
    video_url: Optional[str] = None      # 生成后的视频URL
    ad_titles: list[str] = field(default_factory=list)
    suggested_audience: str = ""         # 人群建议
    bundle_json: str = ""                # 完整 Creative Bundle JSON（含 storyboard/titles/audience）
    user_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 效果数据（由第5层反馈层回填）
    has_performance_data: bool = False
    total_cost: float = 0.0
    roi: float = 0.0
    avg_ctr: float = 0.0
    avg_completion_rate: float = 0.0
    performance_star: int = 0            # 1-5 星

    def to_embedding_text(self) -> str:
        """构建用于向量化的文本"""
        return f"{self.product_name} {self.category} {self.script_type} {self.hook_type} {self.hook} {self.visual_style}"

    def to_metadata(self) -> dict:
        return {
            "product_name": self.product_name,
            "category": self.category,
            "script_type": self.script_type,
            "hook": self.hook,
            "hook_type": self.hook_type,
            "visual_style": self.visual_style,
            "wan22_prompt": self.wan22_prompt,
            "video_url": self.video_url or "",
            "ad_titles": ",".join(self.ad_titles),
            "suggested_audience": self.suggested_audience,
            "bundle_json": self.bundle_json[:8000] if self.bundle_json else "",
            "user_id": self.user_id,
            "created_at": self.created_at,
            "has_performance_data": self.has_performance_data,
            "total_cost": self.total_cost,
            "roi": self.roi,
            "avg_ctr": self.avg_ctr,
            "avg_completion_rate": self.avg_completion_rate,
            "performance_star": self.performance_star,
        }


# ═══════════════════════════════════════════════════
# 记忆3：会话微调
# ═══════════════════════════════════════════════════

@dataclass
class SessionFeedback:
    """单轮微调记录，会话内生效"""
    round_number: int
    user_feedback: str           # 用户原话
    adjustment_type: str         # 调整类型：tone/duration/hook/visual/audience
    adjusted_field: str          # 调整了哪个字段
    adjusted_from: str           # 调整前
    adjusted_to: str             # 调整后
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════
# 记忆4：策略效果联动
# ═══════════════════════════════════════════════════

@dataclass
class StrategyEffect:
    creative_id: str
    user_id: str
    category: str                # 品类
    script_type: str             # 创意类型
    hook_type: str               # 钩子类型
    visual_style: str = ""
    duration: int = 0

    # 定向特征
    target_gender: str = ""
    target_age: str = ""
    target_interests: str = ""

    # 效果指标
    ctr: float = 0.0
    cvr: float = 0.0
    completion_rate: float = 0.0
    roi: float = 0.0
    convert_cost: float = 0.0
    impressions: int = 0
    stat_cost: float = 0.0
    pay_order_count: int = 0
    pay_order_amount: float = 0.0

    user_rating: int = 0          # 1-5 用户主观评分
    feedback_text: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_embedding_text(self) -> str:
        return f"{self.category} {self.script_type} {self.hook_type} {self.visual_style}"


# ═══════════════════════════════════════════════════
# 检索结果模型
# ═══════════════════════════════════════════════════

@dataclass
class SearchResult:
    """统一检索返回"""
    similar_creatives: list[dict] = field(default_factory=list)
    strategy_effects: list[dict] = field(default_factory=list)
    insight: str = ""
