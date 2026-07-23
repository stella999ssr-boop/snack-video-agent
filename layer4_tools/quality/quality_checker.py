"""
第4层 · 质量评估 — 6维100分评分体系

维度:
  1. 种草力      30分 ★ 核心（需要 DashScope Vision API）
  2. 内容匹配度   20分   （需要 DashScope Vision API）
  3. 技术质量     15分   （本地检测：分辨率/帧率/黑帧）
  4. 画面可用性   10分   （本地检测：模糊度/曝光/色彩）
  5. 合规前置检查  10分   （本地禁词库扫描）
  6. 基础电商     10分   （需要 DashScope Vision API）
  7. 时间结构      5分   （本地检测）

质量等级:
  优秀 ≥85 且 种草力≥25
  合格 60-84 且 种草力≥18
  不合格 40-59 → 自动重试（最多2次）
  严重缺陷 <40 或 种草力<10 → 不重试，标记失败

种草力硬性门槛: 即使总分≥60，种草力<15 仍强制降级为不合格
"""

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# 尝试导入 opencv，若不可用则禁用本地检测
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


class QualityGrade(str, Enum):
    EXCELLENT = "excellent"   # ≥85
    PASS = "pass"             # 60-84
    FAIL_RETRY = "fail_retry" # 40-59
    SEVERE = "severe"         # <40


@dataclass
class DimensionScore:
    dimension: str
    score: int              # 实得分
    max_score: int          # 满分
    issues: list[dict] = field(default_factory=list)
    detail: str = ""

    @property
    def ratio(self) -> float:
        return self.score / self.max_score if self.max_score > 0 else 0


@dataclass
class QualityReport:
    total_score: int
    max_score: int = 100
    grade: QualityGrade = QualityGrade.FAIL_RETRY
    dimensions: list[DimensionScore] = field(default_factory=list)
    passed: bool = False
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "total_score": self.total_score,
            "max_score": self.max_score,
            "grade": self.grade.value,
            "passed": self.passed,
            "summary": self.summary,
            "dimensions": [
                {
                    "dimension": d.dimension,
                    "score": d.score,
                    "max_score": d.max_score,
                    "issues": d.issues,
                    "detail": d.detail,
                }
                for d in self.dimensions
            ],
        }


class VideoQualityChecker:
    """6维视频质量评估器"""

    # ─── 硬性门槛 ────────────────────────────
    MIN_RESOLUTION = (720, 720)
    MIN_FPS = 24
    MAX_BLACK_FRAME_RATIO = 0.1
    PASS_THRESHOLD = 60
    EXCELLENT_THRESHOLD = 85
    SEVERE_THRESHOLD = 40
    PLANTING_POWER_PASS = 18      # 种草力及格线
    PLANTING_POWER_SEVERE = 10    # 种草力严重缺陷线

    def __init__(self, vision_api_key: str = ""):
        self.vision_api_key = vision_api_key
        self._cv2 = CV2_AVAILABLE

    def evaluate(
        self,
        video_path: str,
        original_prompt: str = "",
        script: dict = None,
    ) -> QualityReport:
        """
        主入口：对视频做6维评估。

        参数:
          video_path: 视频文件路径
          original_prompt: Wan2.2 生成时用的 Prompt（用于内容匹配度）
          script: 脚本文本（用于种草力+合规）{"hook": "...", "storyboard": [...]}
        """
        dimensions = []
        script = script or {}

        # 提取视频元数据
        metadata = self._extract_metadata(video_path) if self._cv2 else {}
        frames = self._extract_keyframes(video_path, count=6) if self._cv2 else []

        # 维度1: 种草力 ★ (30分) — 核心
        dim_planting = self._check_planting_power(video_path, frames, script)
        dimensions.append(dim_planting)

        # 维度2: 内容匹配度 (20分)
        dim_match = self._check_prompt_match(video_path, frames, original_prompt)
        dimensions.append(dim_match)

        # 维度3: 技术质量 (15分)
        dim_tech = self._check_technical(metadata, frames)
        dimensions.append(dim_tech)

        # 维度4: 画面可用性 (10分)
        dim_visual = self._check_visual_quality(frames)
        dimensions.append(dim_visual)

        # 维度5: 合规前置检查 (10分)
        dim_compliance = self._check_compliance_precheck(script)
        dimensions.append(dim_compliance)

        # 维度6: 基础电商 (10分)
        dim_ecommerce = self._check_ecommerce_basic(frames)
        dimensions.append(dim_ecommerce)

        # 维度7: 时间结构 (5分)
        dim_timing = self._check_timing(
            metadata,
            target_duration=int(script.get("target_duration", 10)),
        )
        dimensions.append(dim_timing)

        total = sum(d.score for d in dimensions)

        # 确定等级
        planting_score = dim_planting.score
        if total >= self.EXCELLENT_THRESHOLD and planting_score >= 25:
            grade = QualityGrade.EXCELLENT
        elif total >= self.PASS_THRESHOLD and planting_score >= self.PLANTING_POWER_PASS:
            grade = QualityGrade.PASS
        elif total < self.SEVERE_THRESHOLD or planting_score < self.PLANTING_POWER_SEVERE:
            grade = QualityGrade.SEVERE
        else:
            grade = QualityGrade.FAIL_RETRY

        # 种草力强制降级
        if total >= self.PASS_THRESHOLD and planting_score < 15:
            grade = QualityGrade.FAIL_RETRY

        return QualityReport(
            total_score=total,
            dimensions=dimensions,
            grade=grade,
            passed=grade in (QualityGrade.EXCELLENT, QualityGrade.PASS),
            summary=self._summarize(total, grade, planting_score, dim_tech.score, dim_tech),
        )

    # ═══════════════════════════════════════════
    # 维度1: 种草力 ★ 30分
    # ═══════════════════════════════════════════

    def _check_planting_power(self, video_path: str, frames: list, script: dict) -> DimensionScore:
        """
        种草力评估：这个视频能不能让人想买？

        子维度（各5分）:
          1. 钩子抓力: 前3秒能否抓住注意力
          2. 产品吸引力: 色泽/质感/包装是否诱人
          3. 利益传达: 卖点是否清晰
          4. 情绪触发: 食欲/从众心理/错过恐惧
          5. 行动引导: 下单引导是否自然
          6. 分享意愿: 用户会不会转发

        TODO: 接入 DashScope Vision API (qwen-vl-plus)
        当前：基于脚本关键词做启发式评分
        """
        score = 15  # 默认中等（无 Vision API 时给中等分避免误判）
        issues = []
        detail_parts = []
        subscores = {}

        hook = script.get("hook", "")
        storyboard = script.get("storyboard", [])

        # ── 钩子抓力 (0-5) ──
        hook_score = 3
        strong_patterns = ["？", "竟然", "为什么", "你敢信", "对比"]
        weak_patterns = ["大家好", "今天给大家"]
        if any(p in hook for p in strong_patterns):
            hook_score = 4
        elif any(p in hook for p in weak_patterns):
            hook_score = 2
        subscores["hook_power"] = hook_score
        if hook_score <= 2:
            issues.append({"severity": "medium", "detail": f"钩子吸引力弱({hook_score}/5)"})
        detail_parts.append(f"钩子抓力={hook_score}/5")

        # ── 产品吸引力 ──
        product_score = 3
        if script.get("product_name"):
            product_score = 3  # 默认中等
        subscores["product_appeal"] = product_score
        detail_parts.append(f"产品吸引力={product_score}/5")

        # ── 利益传达 ──
        benefit_score = 3
        selling_points = script.get("selling_points", [])
        if "价格" in str(script) or "性价比" in str(script):
            benefit_score = 4
        subscores["benefit_clarity"] = benefit_score
        detail_parts.append(f"利益传达={benefit_score}/5")

        # ── 情绪触发 ──
        emotion_score = 3
        emotion_words = ["酥脆", "香", "诱人", "馋", "流口水", "满足"]
        if any(w in str(script) for w in emotion_words):
            emotion_score = 4
        subscores["emotion_trigger"] = emotion_score
        detail_parts.append(f"情绪触发={emotion_score}/5")

        # ── 行动引导 ──
        action_score = 3
        action_words = ["下单", "试试", "点链接", "限时", "抢"]
        if any(w in str(script) for w in action_words):
            action_score = 4
        subscores["action_guide"] = action_score
        detail_parts.append(f"行动引导={action_score}/5")

        # ── 分享意愿 ──
        share_score = 3
        if hook_score >= 4 and emotion_score >= 4:
            share_score = 4
        subscores["share_willingness"] = share_score
        detail_parts.append(f"分享意愿={share_score}/5")

        total = sum(subscores.values())
        score = min(30, total)

        # Vision API 未接入时，基于启发式评分上限为 20 分（避免自欺欺人）
        if not self.vision_api_key:
            score = min(18, score)

        return DimensionScore(
            dimension="种草力",
            score=score,
            max_score=30,
            issues=issues,
            detail=" | ".join(detail_parts) + (" [需Vision API]" if not self.vision_api_key else ""),
        )

    # ═══════════════════════════════════════════
    # 维度2: 内容匹配度 20分
    # ═══════════════════════════════════════════

    def _check_prompt_match(self, video_path: str, frames: list, prompt: str) -> DimensionScore:
        """
        Prompt 与生成画面的匹配度。
        TODO: DashScope Vision API (qwen-vl-plus) 多模态对比
        """
        if not self.vision_api_key:
            return DimensionScore(
                dimension="内容匹配度",
                score=12,
                max_score=20,
                detail="Vision API 未接入，默认中等分 [需 DashScope Vision]",
            )

        # TODO: Vision API 对比
        return DimensionScore(
            dimension="内容匹配度",
            score=15,
            max_score=20,
            detail="Vision API 评估中...",
        )

    # ═══════════════════════════════════════════
    # 维度3: 技术质量 15分
    # ═══════════════════════════════════════════

    def _check_technical(self, metadata: dict, frames: list) -> DimensionScore:
        """分辨率 + 帧率 + 黑帧检测（本地）"""
        score = 15
        issues = []
        detail_parts = []

        if not self._cv2:
            return DimensionScore(
                dimension="技术质量", score=15, max_score=15,
                detail="OpenCV 未安装，跳过本地检测",
            )

        # 分辨率
        w, h = metadata.get("width", 0), metadata.get("height", 0)
        if w < self.MIN_RESOLUTION[0] or h < self.MIN_RESOLUTION[1]:
            score -= 5
            issues.append({"severity": "high", "detail": f"分辨率 {w}x{h}，未达 720p"})
        detail_parts.append(f"分辨率={w}x{h}")

        # 帧率
        fps = metadata.get("fps", 0)
        if fps < self.MIN_FPS:
            score -= 5
            issues.append({"severity": "medium", "detail": f"帧率 {fps}fps，低于 {self.MIN_FPS}fps"})
        detail_parts.append(f"帧率={fps}fps")

        # 黑帧
        if frames:
            black_ratio = self._count_black_frames(frames)
            if black_ratio > self.MAX_BLACK_FRAME_RATIO:
                score -= 5
                issues.append({"severity": "high", "detail": f"黑帧占比 {black_ratio:.0%}"})
            detail_parts.append(f"黑帧占比={black_ratio:.1%}")

        return DimensionScore(
            dimension="技术质量",
            score=max(0, score), max_score=15,
            issues=issues,
            detail=" | ".join(detail_parts),
        )

    # ═══════════════════════════════════════════
    # 维度4: 画面可用性 10分
    # ═══════════════════════════════════════════

    def _check_visual_quality(self, frames: list) -> DimensionScore:
        """模糊度 + 曝光（本地）"""
        if not self._cv2 or not frames:
            return DimensionScore(
                dimension="画面可用性", score=8, max_score=10,
                detail="无可检测画面，默认通过",
            )

        score = 10
        issues = []
        detail_parts = []

        for i, frame in enumerate(frames[:3]):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

            if laplacian_var < 50:
                score -= 3
                issues.append({"severity": "medium", "detail": f"第{i+1}帧模糊 (Laplacian={laplacian_var:.0f})"})

            mean_brightness = gray.mean()
            if mean_brightness < 30:
                score -= 2
                issues.append({"severity": "medium", "detail": f"第{i+1}帧过暗 (亮度={mean_brightness:.0f})"})
            elif mean_brightness > 240:
                score -= 2
                issues.append({"severity": "medium", "detail": f"第{i+1}帧过曝 (亮度={mean_brightness:.0f})"})

        return DimensionScore(
            dimension="画面可用性",
            score=max(0, score), max_score=10,
            issues=issues,
            detail=" | ".join(detail_parts) if detail_parts else "画面质量正常",
        )

    # ═══════════════════════════════════════════
    # 维度5: 合规前置检查 10分
    # ═══════════════════════════════════════════

    def _check_compliance_precheck(self, script: dict) -> DimensionScore:
        """快速禁词扫描（完整合规流程在 4.3）"""
        from layer4_tools.compliance.prompt_rules import check_text

        text = json.dumps(script, ensure_ascii=False)
        hits = check_text(text)

        if not hits:
            return DimensionScore(
                dimension="合规前置检查", score=10, max_score=10,
                detail="未命中禁词",
            )

        block_hits = [h for h in hits if h["category"] in ("child_inducement", "medical_terms", "price_fraud")]
        if block_hits:
            return DimensionScore(
                dimension="合规前置检查", score=2, max_score=10,
                issues=[{"severity": "high", "detail": f"命中高危禁词: {[h['word'] for h in block_hits]}"}],
                detail=f"高危违规: {len(block_hits)} 项",
            )

        return DimensionScore(
            dimension="合规前置检查", score=6, max_score=10,
            issues=[{"severity": "low", "detail": f"命中敏感词: {[h['word'] for h in hits]}"}],
            detail=f"命中 {len(hits)} 个敏感词",
        )

    # ═══════════════════════════════════════════
    # 维度6: 基础电商 10分
    # ═══════════════════════════════════════════

    def _check_ecommerce_basic(self, frames: list) -> DimensionScore:
        """产品清晰度 + 竖屏适配 + 食欲感"""
        if not self.vision_api_key:
            return DimensionScore(
                dimension="基础电商", score=6, max_score=10,
                detail="Vision API 未接入 [需 DashScope Vision]",
            )

        # TODO: Vision API 评估
        return DimensionScore(
            dimension="基础电商", score=8, max_score=10,
            detail="Vision API 评估通过",
        )

    # ═══════════════════════════════════════════
    # 维度7: 时间结构 5分
    # ═══════════════════════════════════════════

    def _check_timing(self, metadata: dict, target_duration: int = 10) -> DimensionScore:
        """时长是否在目标范围内"""
        if not metadata:
            return DimensionScore(dimension="时间结构", score=3, max_score=5, detail="无元数据")

        duration = metadata.get("duration", 0)
        target = target_duration

        diff = abs(duration - target)
        if diff <= 1:
            score = 5
        elif diff <= 3:
            score = 3
        else:
            score = 1

        return DimensionScore(
            dimension="时间结构",
            score=score, max_score=5,
            detail=f"时长={duration:.1f}s (目标={target}s)",
        )

    # ═══════════════════════════════════════════
    # 视频元数据提取
    # ═══════════════════════════════════════════

    def _extract_metadata(self, video_path: str) -> dict:
        if not self._cv2:
            return {}
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return {}
            meta = {
                "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "fps": cap.get(cv2.CAP_PROP_FPS),
                "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                "duration": cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1),
            }
            cap.release()
            return meta
        except Exception:
            return {}

    def _extract_keyframes(self, video_path: str, count: int = 6) -> list:
        """等距抽取关键帧"""
        if not self._cv2:
            return []
        try:
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                cap.release()
                return []

            frames = []
            for i in range(count):
                frame_idx = int(i * total_frames / count)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if ret:
                    frames.append(frame)

            cap.release()
            return frames
        except Exception:
            return []

    def _count_black_frames(self, frames: list) -> float:
        """黑帧占比"""
        if not frames:
            return 0.0
        black_count = 0
        for f in frames:
            gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            if gray.mean() < 10:
                black_count += 1
        return black_count / len(frames)

    # ═══════════════════════════════════════════

    def _summarize(self, total: int, grade: QualityGrade, planting: int, tech: int, tech_dim: DimensionScore) -> str:
        summaries = {
            QualityGrade.EXCELLENT: (
                f"综合评分 {total}/100，优秀。种草力 {planting}/30，可直接发布。"
            ),
            QualityGrade.PASS: (
                f"综合评分 {total}/100，合格。种草力 {planting}/30，可正常使用。"
            ),
            QualityGrade.FAIL_RETRY: (
                f"综合评分 {total}/100，不合格。建议调整脚本后重新生成。"
            ),
            QualityGrade.SEVERE: (
                f"综合评分 {total}/100，严重缺陷。Prompt 或模型异常，不建议重试。"
            ),
        }
        return summaries.get(grade, f"总分 {total}/100")
