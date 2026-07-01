"""
第7层 · 输出层 — 投放效果回流闭环

核心原则：只读不写。从千川获取已投放素材的效果数据，回流到记忆层。

组件:
  - QianchuanTokenManager: OAuth2.0 只读授权
  - CreativeAdLinker: 素材↔广告手动关联
  - ReportCollector: 定时拉取效果数据
  - FeedbackWriter: 效果数据写入记忆层
  - SchedulerStub: 无 Celery 依赖的轻量版
"""

from .schemas import (
    QianchuanToken, CreativeAdLink,
    CreativePerformance, CreativePerformanceSummary,
    FeedbackResult,
)
from .token_manager import QianchuanTokenManager
from .linker import CreativeAdLinker
from .collector import ReportCollector
from .feedback_writer import FeedbackWriter
from .celery_app import BEAT_SCHEDULE, SchedulerStub

__all__ = [
    "QianchuanToken", "CreativeAdLink",
    "CreativePerformance", "CreativePerformanceSummary",
    "FeedbackResult",
    "QianchuanTokenManager", "CreativeAdLinker",
    "ReportCollector", "FeedbackWriter",
    "BEAT_SCHEDULE", "SchedulerStub",
]
