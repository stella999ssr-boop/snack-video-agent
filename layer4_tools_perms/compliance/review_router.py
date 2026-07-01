"""
第三层合规防线：分流路由 + 重试逻辑

风险评估结果 → 分流决策：
  - 低风险: 80% 自动通过, 20% 随机抽审
  - 中风险: 自动重试(最多2次) → 失败转人工
  - 高风险: 自动重试(最多2次) → 失败转人工
"""

import random
from enum import Enum
from dataclasses import dataclass

from .auto_checker import ComplianceReport, ComplianceAutoChecker


class ReviewDecision(str, Enum):
    AUTO_PASS = "auto_pass"           # 自动通过，直接入库
    RANDOM_AUDIT = "random_audit"     # 随机抽审，转人工
    AUTO_RETRY = "auto_retry"         # 自动重试（Agent 调整脚本）
    MANUAL_REVIEW = "manual_review"   # 转人工审批


@dataclass
class RouteResult:
    decision: ReviewDecision
    reason: str
    retry_count: int = 0
    max_retries: int = 2
    needs_human: bool = False
    notes: str = ""


class ReviewRouter:
    """第三层：合规分流 + 重试逻辑"""

    LOW_RISK_SAMPLE_RATE = 0.2       # 低风险随机抽审比例
    MAX_AUTO_RETRIES = 2             # 最大自动重试次数

    def route(self, report: ComplianceReport, retry_count: int = 0) -> RouteResult:
        """根据风险评估结果做出分流决策"""
        risk = report.risk_level
        remaining_retries = self.MAX_AUTO_RETRIES - retry_count

        if risk == "low":
            return self._handle_low_risk()

        if risk == "medium":
            return self._handle_elevated_risk(
                risk="medium", retry_count=retry_count,
                remaining_retries=remaining_retries,
                report=report,
            )

        if risk == "high":
            return self._handle_elevated_risk(
                risk="high", retry_count=retry_count,
                remaining_retries=remaining_retries,
                report=report,
            )

        return RouteResult(
            decision=ReviewDecision.MANUAL_REVIEW,
            reason="未知风险等级，默认转人工",
            needs_human=True,
        )

    def _handle_low_risk(self) -> RouteResult:
        """低风险：80% 直接通过，20% 随机抽审"""
        if random.random() < self.LOW_RISK_SAMPLE_RATE:
            return RouteResult(
                decision=ReviewDecision.RANDOM_AUDIT,
                reason="低风险随机抽审（20% 概率）",
                needs_human=True,
                notes="标准抽审流程，非质量问题",
            )
        return RouteResult(
            decision=ReviewDecision.AUTO_PASS,
            reason="低风险自动通过",
        )

    def _handle_elevated_risk(
        self,
        risk: str,
        retry_count: int,
        remaining_retries: int,
        report: ComplianceReport,
    ) -> RouteResult:
        """中/高风险处理"""
        # 收集违规词供 Agent 参考
        all_hits = []
        for ch in [report.text_check, report.asr_check, report.ocr_check]:
            if ch and ch.risk_words:
                all_hits.extend(ch.risk_words)

        if remaining_retries > 0:
            return RouteResult(
                decision=ReviewDecision.AUTO_RETRY,
                reason=f"{risk}风险，还有 {remaining_retries} 次重试机会",
                retry_count=retry_count,
                max_retries=self.MAX_AUTO_RETRIES,
                notes=f"请调整脚本避免以下词语: {', '.join(all_hits)}",
            )

        return RouteResult(
            decision=ReviewDecision.MANUAL_REVIEW,
            reason=f"{risk}风险，{self.MAX_AUTO_RETRIES} 次自动重试用尽，转人工审批",
            retry_count=retry_count,
            max_retries=self.MAX_AUTO_RETRIES,
            needs_human=True,
            notes=f"违规词: {', '.join(all_hits)}。请人工判断是否发布。",
        )

    def can_retry(self, retry_count: int) -> bool:
        return retry_count < self.MAX_AUTO_RETRIES


# ═══════════════════════════════════════════════════
# 便捷函数：一键合规检查
# ═══════════════════════════════════════════════════

def run_compliance_pipeline(
    script: str,
    ad_titles: list[str],
    video_path: str = "",
    retry_count: int = 0,
) -> RouteResult:
    """
    一键执行合规全流程：文本检测 → 风险评估 → 分流决策
    Agent 在生成视频后调用此函数。
    """
    checker = ComplianceAutoChecker()
    report = checker.check(script=script, ad_titles=ad_titles, video_path=video_path)

    router = ReviewRouter()
    result = router.route(report, retry_count=retry_count)

    return result
