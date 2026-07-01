"""
Celery Beat 定时任务配置

每天凌晨 3:17 触发千川效果数据拉取。
使用 Redis 或 SQLite 作为 broker（开发环境可用 SQLite）。

启动方式:
    celery -A layer7_output.celery_app worker --beat -l info

或在代码中启动:
    celery_app.start()
"""

import os
from datetime import datetime


# ═══════════════════════════════════════════════════
# Celery 应用配置
# ═══════════════════════════════════════════════════

# 使用环境变量配置 broker，默认使用内存 broker（仅开发环境）
BROKER_URL = os.getenv("CELERY_BROKER_URL", "memory://")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "cache+memory://")

# 定时任务配置（cron 格式）
BEAT_SCHEDULE = {
    "fetch-qianchuan-reports": {
        "task": "layer7_output.collector.fetch_all_reports",
        "schedule": {"hour": 3, "minute": 17},  # 凌晨 3:17
        "options": {"expires": 3600},             # 1 小时后过期
    },
    # 可选：每周策略效果汇总报告
    "weekly-strategy-summary": {
        "task": "layer7_output.feedback_writer.process_all_active",
        "schedule": {"day_of_week": "1", "hour": 4, "minute": 0},  # 每周一凌晨4点
        "options": {"expires": 7200},
    },
}


# ═══════════════════════════════════════════════════
# 无 Celery 依赖的轻量版本（开发/演示用）
# ═══════════════════════════════════════════════════

class SchedulerStub:
    """
    Celery 的轻量替代。

    当没有 Redis/RabbitMQ 时，提供同步调用接口。
    celery_app 可以设置为 None（不需要 Celery）或
    使用此 stub 在开发环境中直接调用定时任务逻辑。
    """

    def __init__(self, collector=None, feedback_writer=None):
        self.collector = collector
        self.feedback_writer = feedback_writer

    def fetch_all_reports(self) -> dict:
        """手动触发全量拉取"""
        if self.collector is None:
            return {"error": "collector not initialized"}
        return self.collector.fetch_all_reports()

    def process_all_active(self) -> dict:
        """手动触发全量回流"""
        if self.feedback_writer is None:
            return {"error": "feedback_writer not initialized"}
        return self.feedback_writer.process_all_active()

    def run_daily_job(self) -> dict:
        """
        模拟每日定时任务：拉取 → 回流。

        在没有 Celery 的环境中，可以通过外部 cron / 计划任务调用此方法。
        """
        print(f"[{datetime.now().isoformat()}] 开始每日反馈任务...")

        fetch_result = self.fetch_all_reports()
        print(f"  拉取完成: {fetch_result}")

        if fetch_result.get("success", 0) > 0:
            process_result = self.process_all_active()
            print(f"  回流完成: {process_result}")

        return {"fetch": fetch_result, "process": "ok"}
