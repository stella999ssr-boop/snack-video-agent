"""
第4层 · 工具 + 质量评估 + 合规防线

工具: Wan2.2 视频生成 (t2v / i2v)
质量: 6维100分评估体系（种草力30分最高权重）
合规: 三层防线（Prompt禁词 → API检测 → 人工审批分流）
"""

from .tools import Wan22Tool, Wan22Result, TaskStatus
from .quality import VideoQualityChecker, QualityReport, QualityGrade, DimensionScore
from .compliance import (
    ComplianceAutoChecker, ComplianceReport, ChannelResult,
    ReviewRouter, RouteResult, ReviewDecision,
    run_compliance_pipeline,
    check_text, get_all_forbidden_words, get_prompt_rules_text,
)

__all__ = [
    # 工具
    "Wan22Tool", "Wan22Result", "TaskStatus",
    # 质量
    "VideoQualityChecker", "QualityReport", "QualityGrade", "DimensionScore",
    # 合规
    "ComplianceAutoChecker", "ComplianceReport", "ChannelResult",
    "ReviewRouter", "RouteResult", "ReviewDecision",
    "run_compliance_pipeline",
    "check_text", "get_all_forbidden_words", "get_prompt_rules_text",
]
