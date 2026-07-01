"""
第5层 · 反馈层 — 数据模型

核心原则：只读不写。从千川获取已投放素材的效果数据，回流到记忆层。
"""

from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════
# OAuth Token
# ═══════════════════════════════════════════════════

@dataclass
class QianchuanToken:
    user_id: str
    access_token: str
    refresh_token: str
    expires_at: str                          # ISO datetime
    advertiser_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════
# 素材↔广告关联
# ═══════════════════════════════════════════════════

@dataclass
class CreativeAdLink:
    creative_id: str                         # 系统内素材ID
    ad_id: str                               # 千川广告ID
    advertiser_id: str                       # 千川广告主ID
    user_id: str
    linked_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════
# 每日效果数据
# ═══════════════════════════════════════════════════

@dataclass
class CreativePerformance:
    creative_id: str
    ad_id: str
    date: str                                # YYYY-MM-DD

    # 消耗与展示
    stat_cost: float = 0.0                   # 消耗（元）
    show_cnt: int = 0                        # 展示量
    click_cnt: int = 0                       # 点击量

    # 核心指标
    ctr: float = 0.0                         # 点击率
    cvr: float = 0.0                         # 转化率
    completion_rate: float = 0.0             # 完播率
    play_3s_rate: float = 0.0               # 3秒有效播放率

    # 转化指标
    pay_order_count: int = 0                 # 成交订单数
    pay_order_amount: float = 0.0            # 成交金额
    roi: float = 0.0                         # 支付ROI
    convert_cost: float = 0.0                # 转化成本

    recorded_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ═══════════════════════════════════════════════════
# 汇总效果
# ═══════════════════════════════════════════════════

@dataclass
class CreativePerformanceSummary:
    creative_id: str
    ad_id: str
    user_id: str

    # 计量
    total_cost: float = 0.0
    total_impressions: int = 0
    total_clicks: int = 0
    total_orders: int = 0
    total_revenue: float = 0.0

    # 加权平均
    avg_ctr: float = 0.0
    avg_cvr: float = 0.0
    avg_completion_rate: float = 0.0
    avg_roi: float = 0.0
    avg_convert_cost: float = 0.0

    # 评星
    performance_star: int = 0                # 1-5 星（基于ROI自动评）

    days_collected: int = 0
    first_date: str = ""
    last_date: str = ""

    def compute_star(self):
        if self.avg_roi >= 5.0: self.performance_star = 5
        elif self.avg_roi >= 3.0: self.performance_star = 4
        elif self.avg_roi >= 1.5: self.performance_star = 3
        elif self.avg_roi >= 1.0: self.performance_star = 2
        else: self.performance_star = 1


# ═══════════════════════════════════════════════════
# 反馈结果（写入记忆后返回）
# ═══════════════════════════════════════════════════

@dataclass
class FeedbackResult:
    creative_id: str
    written_to_strategy: bool = False         # 是否写入记忆4
    written_to_archive: bool = False          # 是否更新记忆2
    summary: Optional[CreativePerformanceSummary] = None
    error: str = ""
