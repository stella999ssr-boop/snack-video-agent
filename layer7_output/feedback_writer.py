"""
效果数据回流 → 记忆层

采集器拉取效果数据后，由本模块写入记忆2（历史素材）和记忆4（策略效果），
驱动下一次素材生成更聪明。

写入目标:
  - 记忆4 (strategy_effects): 策略效果聚合 → Agent search_kb 可检索
  - 记忆2 (creative_archive): 更新素材的 performance 字段 → 搜索时带效果信息
"""

from datetime import datetime

from layer3_memory.memory_manager import MemoryManager
from layer3_memory.schemas import StrategyEffect

from .collector import ReportCollector
from .schemas import CreativePerformanceSummary, FeedbackResult


class FeedbackWriter:
    """效果数据写入记忆层"""

    def __init__(self, memory: MemoryManager, collector: ReportCollector):
        self.memory = memory
        self.collector = collector

    def process_creative(self, creative_id: str, ad_id: str, user_id: str,
                         category: str = "", script_type: str = "", hook_type: str = "") -> FeedbackResult:
        """
        处理单个素材的效果反馈：汇总 → 写入记忆4 + 更新记忆2

        由采集器在拉取数据后调用。
        """
        result = FeedbackResult(creative_id=creative_id)

        # 1. 汇总效果数据
        summary_data = self.collector.get_summary(creative_id, ad_id)
        if not summary_data or summary_data.get("days", 0) == 0:
            result.error = "无效果数据"
            return result

        summary = CreativePerformanceSummary(
            creative_id=creative_id,
            ad_id=ad_id,
            user_id=user_id,
            total_cost=summary_data["total_cost"] or 0,
            total_impressions=summary_data["total_impressions"] or 0,
            total_clicks=summary_data["total_clicks"] or 0,
            total_orders=summary_data["total_orders"] or 0,
            total_revenue=summary_data["total_revenue"] or 0,
            avg_ctr=summary_data["avg_ctr"] or 0,
            avg_cvr=summary_data["avg_cvr"] or 0,
            avg_completion_rate=summary_data["avg_completion"] or 0,
            avg_roi=summary_data["avg_roi"] or 0,
            avg_convert_cost=summary_data["avg_convert_cost"] or 0,
            days_collected=summary_data["days"],
            first_date=summary_data["first_date"],
            last_date=summary_data["last_date"],
        )
        summary.compute_star()
        result.summary = summary

        # 2. 写入记忆4：策略效果联动
        effect = StrategyEffect(
            creative_id=creative_id,
            user_id=user_id,
            category=category,
            script_type=script_type,
            hook_type=hook_type,
            ctr=summary.avg_ctr,
            cvr=summary.avg_cvr,
            completion_rate=summary.avg_completion_rate,
            roi=summary.avg_roi,
            convert_cost=summary.avg_convert_cost,
            impressions=summary.total_impressions,
            stat_cost=summary.total_cost,
            pay_order_count=summary.total_orders,
            pay_order_amount=summary.total_revenue,
            recorded_at=datetime.now().isoformat(),
        )
        self.memory.record_strategy_effect(effect)
        result.written_to_strategy = True

        # 3. 更新记忆2：历史素材 performance 字段
        try:
            self.memory.creatives.update_performance(
                creative_id=creative_id,
                total_cost=summary.total_cost,
                roi=summary.avg_roi,
                avg_ctr=summary.avg_ctr,
                avg_completion_rate=summary.avg_completion_rate,
                performance_star=summary.performance_star,
            )
            result.written_to_archive = True
        except Exception as e:
            result.error = f"更新记忆2失败: {e}"

        return result

    def process_all_active(self) -> dict:
        """
        处理所有活跃关联 → 写入记忆层。
        Celery 定时任务在拉取数据后调用此方法完成闭环。
        """
        links = self.collector.linker.get_active_links()
        results = {
            "total": len(links),
            "processed": 0,
            "success": 0,
            "details": [],
        }

        for link in links:
            creative_id = link["creative_id"]
            ad_id = link["ad_id"]

            # 先拉取最新数据
            try:
                self.collector.fetch_single_report(link)
            except Exception as e:
                results["details"].append({
                    "creative_id": creative_id,
                    "ad_id": ad_id,
                    "status": "fetch_error",
                    "error": str(e),
                })
                continue

            # 再写入记忆
            fb_result = self.process_creative(
                creative_id=creative_id,
                ad_id=ad_id,
                user_id=link["user_id"],
                category=link.get("category", ""),
                script_type=link.get("script_type", ""),
                hook_type=link.get("hook_type", ""),
            )

            results["processed"] += 1
            if fb_result.written_to_strategy:
                results["success"] += 1
            results["details"].append({
                "creative_id": creative_id,
                "ad_id": ad_id,
                "star": fb_result.summary.performance_star if fb_result.summary else 0,
                "roi": fb_result.summary.avg_roi if fb_result.summary else 0,
            })

        return results

    def get_effect_summary_for_agent(self, category: str) -> str:
        """
        为 Agent 生成效果数据摘要（注入到下次素材生成的 prompt 中）。

        Agent 调用此方法获取同品类最新效果数据作为决策参考。
        """
        insight = self.memory.get_strategy_insight(category)
        top = self.memory.get_top_performers(category=category, limit=3)

        if not top:
            return ""

        lines = ["\n## 同品类近期效果数据（来自反馈层）"]
        for i, t in enumerate(top):
            lines.append(
                f"{i+1}. {t['script_type']}+{t['hook_type']}: "
                f"ROI={t['roi']:.1f}, CTR={t['ctr']:.1%}, "
                f"曝光={t['impressions']}"
            )
        lines.append(f"\n数据洞察: {insight}")

        return "\n".join(lines)
