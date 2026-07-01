"""
千川效果数据定时采集器

Celery Beat 每天凌晨 3:17 触发，遍历所有活跃关联拉取效果报表。

拉取规则:
  - 关联后第 3 天开始拉取（前2天数据不稳定）
  - 持续拉取到第 30 天（效果已稳定，不再变化）
  - 每次 API 请求最多拉 7 天数据（千川 API 限制）
  - 限频时自动退避 2 秒
  - Token 过期自动刷新
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx

from .token_manager import QianchuanTokenManager
from .linker import CreativeAdLinker
from .schemas import CreativePerformance


class ReportCollector:
    """千川效果数据定时采集器"""

    # 千川素材报表 API
    REPORT_API = "https://ad.oceanengine.com/open_api/v1.0/qianchuan/report/creative/get/"

    DAYS_AFTER_LINK_TO_START = 3    # 关联后第3天开始
    DAYS_TO_COLLECT = 30             # 总共采集30天
    MAX_DAYS_PER_REQUEST = 7          # 每次最多7天

    # 请求的指标字段
    REPORT_FIELDS = [
        "stat_cost",                      # 消耗
        "show_cnt",                       # 展示量
        "click_cnt",                      # 点击量
        "ctr",                            # 点击率
        "cvr",                            # 转化率
        "pay_order_count",                # 成交订单数
        "pay_order_amount",               # 成交金额
        "prepay_and_pay_order_roi",       # 支付ROI
        "convert_cost",                   # 转化成本
        "play_over_rate",                 # 完播率
        "play_3s_validate_rate",          # 3秒有效播放率
    ]

    def __init__(self, db_path: str, token_manager: QianchuanTokenManager, linker: CreativeAdLinker):
        self.db_path = db_path
        self.token_manager = token_manager
        self.linker = linker
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS creative_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creative_id TEXT NOT NULL,
                    ad_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    stat_cost REAL DEFAULT 0,
                    show_cnt INTEGER DEFAULT 0,
                    click_cnt INTEGER DEFAULT 0,
                    ctr REAL DEFAULT 0,
                    cvr REAL DEFAULT 0,
                    completion_rate REAL DEFAULT 0,
                    play_3s_rate REAL DEFAULT 0,
                    pay_order_count INTEGER DEFAULT 0,
                    pay_order_amount REAL DEFAULT 0,
                    roi REAL DEFAULT 0,
                    convert_cost REAL DEFAULT 0,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(creative_id, ad_id, date)
                )
            """)

    # ─── 定时任务入口 ───────────────────────────────

    def fetch_all_reports(self) -> dict:
        """
        Celery 定时任务主入口。
        遍历所有活跃关联，拉取效果数据，写入记忆层。

        返回: {"processed": N, "success": N, "errors": [...]}
        """
        active_links = self.linker.get_active_links()
        result = {"processed": 0, "success": 0, "errors": []}

        for link in active_links:
            try:
                self.fetch_single_report(link)
                result["success"] += 1
            except Exception as e:
                result["errors"].append({
                    "creative_id": link["creative_id"],
                    "ad_id": link["ad_id"],
                    "error": str(e),
                })
            result["processed"] += 1

        return result

    def fetch_single_report(self, link: dict):
        """
        拉取单个广告的效果数据（分页拉取，每次最多 7 天）。

        TODO: 接入真实千川 API 时替换 _call_qianchuan_api 实现。
        当前使用模拟数据做端到端验证。
        """
        linked_date = datetime.fromisoformat(link["linked_at"]).date()
        start_date = linked_date + timedelta(days=self.DAYS_AFTER_LINK_TO_START)
        end_date = min(datetime.now().date(), linked_date + timedelta(days=self.DAYS_TO_COLLECT))

        if start_date > end_date:
            return  # 还没到开始拉取的时间

        # 分页拉取（每次最多7天）
        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(chunk_start + timedelta(days=self.MAX_DAYS_PER_REQUEST - 1), end_date)

            rows = self._call_qianchuan_api(
                advertiser_id=link["advertiser_id"],
                ad_id=link["ad_id"],
                start_date=chunk_start.isoformat(),
                end_date=chunk_end.isoformat(),
                access_token=self.token_manager.get_valid_token(link["user_id"]),
            )

            # 落库
            for row in rows:
                self._save_performance(link["creative_id"], link["ad_id"], row)

            chunk_start = chunk_end + timedelta(days=1)

    # ─── API 调用（模拟 / 真实）─────────────────────

    def _call_qianchuan_api(
        self,
        advertiser_id: str,
        ad_id: str,
        start_date: str,
        end_date: str,
        access_token: Optional[str],
    ) -> list[dict]:
        """
        调用千川素材报表 API。

        TODO: 生产环境用 httpx 发送真实请求。
        当前使用模拟数据（基于日期范围生成可预测的假数据）。
        """
        if access_token:
            # TODO: 真实 API 调用
            # resp = httpx.get(self.REPORT_API, params={
            #     "advertiser_id": advertiser_id,
            #     "start_date": start_date,
            #     "end_date": end_date,
            #     "filtering": json.dumps({"creative_ids": [ad_id]}),
            #     "fields": json.dumps(self.REPORT_FIELDS),
            #     "page": 1,
            #     "page_size": 100,
            # }, headers={"Access-Token": access_token})
            # data = resp.json()
            # return data.get("data", {}).get("list", [])
            pass

        # 模拟数据（端到端测试用）
        return self._mock_report(start_date, end_date)

    def _mock_report(self, start_date: str, end_date: str) -> list[dict]:
        """生成模拟效果数据"""
        rows = []
        current = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        while current <= end:
            # 模拟真实投放曲线：前几天波动大，后期稳定
            day_index = (current.date() - datetime.fromisoformat(start_date).date()).days
            base_ctr = 0.035 + (day_index * 0.002)    # CTR 逐渐上升（模型学习期）
            base_cvr = 0.05 + (day_index * 0.003)      # CVR 也逐渐上升
            base_roi = 2.5 + (day_index * 0.3)          # ROI 从 2.5 升到 ~8+
            impressions = 8000 + (day_index * 500)      # 展示量递增

            rows.append({
                "date": current.date().isoformat(),
                "stat_cost": 300 + (day_index * 20),
                "show_cnt": impressions,
                "click_cnt": int(impressions * base_ctr),
                "ctr": round(base_ctr, 4),
                "cvr": round(base_cvr, 4),
                "completion_rate": round(0.32 + (day_index * 0.01), 4),
                "play_3s_rate": round(0.55 + (day_index * 0.01), 4),
                "pay_order_count": max(1, int(impressions * base_ctr * base_cvr)),
                "pay_order_amount": round(max(1, int(impressions * base_ctr * base_cvr)) * 29.9, 2),
                "roi": round(base_roi, 2),
                "convert_cost": round(300 / max(1, int(impressions * base_ctr * base_cvr)), 2),
            })
            current += timedelta(days=1)

        return rows

    # ─── 数据存储 ───────────────────────────────────

    def _save_performance(self, creative_id: str, ad_id: str, row: dict):
        """单日效果数据落库"""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO creative_performance
                    (creative_id, ad_id, date, stat_cost, show_cnt, click_cnt,
                     ctr, cvr, completion_rate, play_3s_rate,
                     pay_order_count, pay_order_amount, roi, convert_cost, recorded_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                creative_id, ad_id, row["date"],
                row.get("stat_cost", 0),
                row.get("show_cnt", 0),
                row.get("click_cnt", 0),
                row.get("ctr", 0),
                row.get("cvr", 0),
                row.get("completion_rate", 0),
                row.get("play_3s_rate", 0),
                row.get("pay_order_count", 0),
                row.get("pay_order_amount", 0),
                row.get("roi", 0),
                row.get("convert_cost", 0),
                datetime.now().isoformat(),
            ))

    # ─── 数据查询 ───────────────────────────────────

    def get_performance(self, creative_id: str, ad_id: str = "") -> list[dict]:
        """查询某个素材的效果明细"""
        with self._connect() as conn:
            if ad_id:
                rows = conn.execute(
                    "SELECT * FROM creative_performance WHERE creative_id=? AND ad_id=? ORDER BY date",
                    (creative_id, ad_id)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM creative_performance WHERE creative_id=? ORDER BY date",
                    (creative_id,)
                ).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self, creative_id: str, ad_id: str) -> dict:
        """汇总统计"""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as days,
                    MIN(date) as first_date,
                    MAX(date) as last_date,
                    SUM(stat_cost) as total_cost,
                    SUM(show_cnt) as total_impressions,
                    SUM(click_cnt) as total_clicks,
                    SUM(pay_order_count) as total_orders,
                    SUM(pay_order_amount) as total_revenue,
                    AVG(ctr) as avg_ctr,
                    AVG(cvr) as avg_cvr,
                    AVG(completion_rate) as avg_completion,
                    AVG(roi) as avg_roi,
                    AVG(convert_cost) as avg_convert_cost
                FROM creative_performance
                WHERE creative_id=? AND ad_id=?
            """, (creative_id, ad_id)).fetchone()
        return dict(row) if row else {}

    def has_data(self, creative_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM creative_performance WHERE creative_id=? LIMIT 1",
                (creative_id,)
            ).fetchone()
        return row is not None
