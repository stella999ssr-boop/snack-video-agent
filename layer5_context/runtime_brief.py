"""
两写②：InjectRuntimeConfig() — 生成运行时简报

每轮任务启动前，基于聚合的 TaskContextForEnv 生成一份结构化简报。
输出两种格式：
  1. NL Brief（自然语言）→ 注入 LLM system/user prompt
  2. JSON Brief（结构化）→ 给工具/脚本读取

简报遵循"按需注入"原则：每一部分只包含本轮任务相关的子集。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime

from .task_context import TaskContextForEnv


@dataclass
class CreativeBrief:
    """
    运行时创意简报 — 注入 LLM prompt 的结构化上下文

    替代原先的 _build_user_message() 字符串拼接。
    每部分按优先级排列，LLM 应优先关注高位部分。
    """

    # ── Priority 1: 任务核心 ──
    product_name: str = ""
    category: str = ""
    task_goal: str = "生成一条抖音短视频素材方案（脚本+视频+文案+人群）"
    selling_points: list[str] = field(default_factory=list)
    taste_tags: list[str] = field(default_factory=list)
    price_info: dict = field(default_factory=dict)

    # ── Priority 2: 策略参考 ──
    category_insight: str = ""                    # 同品类策略洞察（Memory 4）
    top_strategies: list[dict] = field(default_factory=list)  # Top ROI 策略
    similar_creatives_brief: str = ""             # 相似素材简况（Memory 2）

    # ── Priority 3: 用户偏好 ──
    preferred_hook: str = ""
    preferred_visual: str = ""
    brand_tone: str = ""
    taboo_words: list[str] = field(default_factory=list)

    # ── Priority 4: 会话微调 ──
    session_feedback_raw: str = ""                # 前几轮微调（Memory 3）

    # ── 可用技能 ──
    skill_names: list[str] = field(default_factory=list)

    # ── 约束 ──
    duration_range: str = "15-30"
    must_comply: str = (
        "1. 禁止虚假宣传/极限词 2. 食品不得暗示医疗功效 "
        "3. 价格对比需真实 4. 不得贬低竞品"
    )

    def to_nl(self) -> str:
        """
        转为自然语言文本 — 注入 LLM prompt。
        按优先级分段，高优先级在前。
        """
        sections = []

        # P1: 产品信息
        product_lines = [
            "## 产品信息",
            f"- 商品名称: {self.product_name}",
            f"- 品类: {self.category}",
        ]
        if self.selling_points:
            product_lines.append(f"- 卖点: {', '.join(self.selling_points)}")
        if self.taste_tags:
            product_lines.append(f"- 口味: {', '.join(self.taste_tags)}")
        if self.price_info:
            price = self.price_info
            product_lines.append(
                f"- 价格: {price.get('unit_price', '?')}元 "
                f"(原价{price.get('original_price', '?')}元)"
            )
        sections.append("\n".join(product_lines))

        # P2: 策略参考
        strategy_lines = ["## 历史策略参考"]
        if self.category_insight:
            strategy_lines.append(f"洞察: {self.category_insight}")
        if self.top_strategies:
            strategy_lines.append("同品类 ROI 最高策略:")
            for s in self.top_strategies[:3]:
                strategy_lines.append(
                    f"  - {s.get('script_type', '?')}+{s.get('hook_type', '?')}: "
                    f"ROI={s.get('avg_roi', 0):.1f}, CTR={s.get('avg_ctr', 0):.1%}"
                )
        if self.similar_creatives_brief:
            strategy_lines.append(f"\n历史相似素材:\n{self.similar_creatives_brief}")
        sections.append("\n".join(strategy_lines))

        # P3: 用户偏好
        pref_parts = []
        if self.preferred_hook:
            pref_parts.append(f"- 偏好钩子: {self.preferred_hook}")
        if self.preferred_visual:
            pref_parts.append(f"- 视觉风格: {self.preferred_visual}")
        if self.brand_tone:
            pref_parts.append(f"- 品牌调性: {self.brand_tone}")
        if self.taboo_words:
            pref_parts.append(f"- 禁忌词: {', '.join(self.taboo_words)}")
        if pref_parts:
            sections.append("## 用户偏好\n" + "\n".join(pref_parts))

        # P4: 历史素材简况
        if self.similar_creatives_brief:
            sections.append(f"## 历史素材简况\n{self.similar_creatives_brief}")

        # P5: 会话微调
        if self.session_feedback_raw:
            sections.append(f"## 本轮微调记录\n{self.session_feedback_raw}")

        # P6: 约束
        sections.append(f"## 约束\n时长: {self.duration_range}s\n{self.must_comply}")

        return "\n\n".join(sections)

    def to_json(self) -> str:
        """转为 JSON 字符串（给工具/脚本读取）"""
        return json.dumps(
            {
                "product": {
                    "name": self.product_name,
                    "category": self.category,
                    "selling_points": self.selling_points,
                    "taste_tags": self.taste_tags,
                    "price": self.price_info,
                },
                "strategy_reference": {
                    "insight": self.category_insight,
                    "top_strategies": self.top_strategies,
                },
                "preferences": {
                    "hook": self.preferred_hook,
                    "visual": self.preferred_visual,
                    "tone": self.brand_tone,
                    "taboo": self.taboo_words,
                },
                "constraints": {
                    "duration_range": self.duration_range,
                    "compliance": self.must_comply,
                },
                "skills": self.skill_names,
                "feedback": self.session_feedback_raw,
            },
            ensure_ascii=False,
            indent=2,
        )

    def to_llm_context(self) -> str:
        """
        生成注入 LLM 的完整上下文（system prompt 尾部 + user message）。
        这是 _build_user_message() 的替代品。
        """
        return self.to_nl()


# ─── 工厂函数 ─────────────────────────────────


def inject_runtime_config(ctx: TaskContextForEnv) -> CreativeBrief:
    """
    从 TaskContextForEnv 生成运行时简报。

    这是 "两写" 的第二写 — 不写文件，生成注入 LLM 的结构化上下文。
    （如果需要写文件，使用 write_context_files()）

    Args:
        ctx: 聚合后的上下文

    Returns:
        CreativeBrief — 可直接 .to_nl() 注入 prompt
    """
    product = ctx.product_info
    features = product.get("features", {})
    price = product.get("price", {})

    # 构建相似素材简况
    similar_brief = ""
    if ctx.historical_creatives:
        items = []
        for c in ctx.historical_creatives[:5]:
            perf = ""
            if c.get("has_performance_data"):
                perf = f" [ROI:{c.get('roi', 0):.1f}, ★{c.get('performance_star', 0)}]"
            items.append(
                f"  - {c.get('script_type', '?')} | "
                f"「{c.get('hook', '')[:30]}」{perf}"
            )
        similar_brief = "\n".join(items)

    brief = CreativeBrief(
        product_name=ctx.product_name,
        category=ctx.category_l2 or ctx.category_l1,
        selling_points=features.get("selling_points", []),
        taste_tags=features.get("taste_tags", []),
        price_info={
            "unit_price": price.get("unit_price", ""),
            "original_price": price.get("original_price", ""),
            "discount_rate": price.get("discount_rate", ""),
        },
        category_insight=ctx.strategy_insight,
        top_strategies=ctx.top_category_strategies,
        similar_creatives_brief=similar_brief,
        preferred_hook=ctx.user_preferences.get("preferred_hook", ""),
        preferred_visual=ctx.user_preferences.get("preferred_visual", ""),
        brand_tone=ctx.user_preferences.get("brand_tone", ""),
        taboo_words=ctx.taboo_words,
        session_feedback_raw=ctx.feedback_summary,
        skill_names=[s.name for s in ctx.available_skills],
    )

    return brief
