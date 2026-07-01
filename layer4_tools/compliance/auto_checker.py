"""
第二层合规防线：多通道 API 自动检测

四通道并行检测：
  1. 文本检测 — 脚本 + 标题，调用阿里云内容安全 + 本地禁词库
  2. ASR 语音检测 — 提取视频音频 → Whisper 转写 → 文本检测
  3. OCR 画面检测 — 关键帧 → DashScope OCR → 检测
  4. 脚本-配音 一致性校验 — 文本相似度对比

当前实现：文本检测使用本地禁词库（无需外部 API）。
ASR/OCR 预留接口，接入阿里云/DashScope 后激活。
"""

import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from typing import Optional

from .prompt_rules import check_text as check_forbidden_words


@dataclass
class ChannelResult:
    """单通道检测结果"""
    channel: str                          # text / asr / ocr / consistency
    passed: bool
    risk_words: list[str] = field(default_factory=list)
    suggestion: str = "pass"              # pass / review / block
    detail: str = ""


@dataclass
class ComplianceReport:
    """四通道检测综合报告"""
    text_check: Optional[ChannelResult] = None
    asr_check: Optional[ChannelResult] = None
    ocr_check: Optional[ChannelResult] = None
    script_asr_similarity: float = 1.0    # 脚本-配音相似度
    risk_level: str = "low"               # low / medium / high
    total_risk_score: int = 0

    def is_clean(self) -> bool:
        return self.risk_level == "low"


class ComplianceAutoChecker:
    """第二层：四通道自动检测"""

    SIMILARITY_THRESHOLD = 0.95           # 脚本-配音相似度阈值
    ASR_ENABLED = False                    # 需要 Whisper + 阿里云
    OCR_ENABLED = False                    # 需要 DashScope OCR

    def __init__(
        self,
        aliyun_access_key: str = "",
        aliyun_secret: str = "",
        dashscope_api_key: str = "",
    ):
        self.aliyun_access_key = aliyun_access_key
        self.aliyun_secret = aliyun_secret
        self.dashscope_api_key = dashscope_api_key

    def check(
        self,
        script: str,
        ad_titles: list[str],
        video_path: str = "",
    ) -> ComplianceReport:
        """
        四通道并行检测入口。
        当前实现：通道1（文本检测）使用本地禁词库始终可用；
        通道2-3 需要外部 API 接入后激活。
        """
        report = ComplianceReport()

        # 通道1: 文本检测（始终可用）
        report.text_check = self._check_text(script, ad_titles)

        # 通道2: ASR 语音检测（需 Whisper + 阿里云）
        if self.ASR_ENABLED and video_path:
            report.asr_check = self._check_asr(video_path)

        # 通道3: OCR 画面检测（需 DashScope OCR）
        if self.OCR_ENABLED and video_path:
            report.ocr_check = self._check_ocr(video_path)

        # 通道4: 脚本-配音一致性（需 ASR 先执行）
        if report.asr_check and report.asr_check.detail:
            report.script_asr_similarity = self._calculate_similarity(
                script, report.asr_check.detail
            )

        # 综合风险评估
        report.risk_level = self._assess_risk(report)
        return report

    # ─── 通道1：文本检测 ────────────────────────────

    def _check_text(self, script: str, ad_titles: list[str]) -> ChannelResult:
        """本地禁词库扫描"""
        full_text = script + " " + " ".join(ad_titles)
        hits = check_forbidden_words(full_text)

        if not hits:
            return ChannelResult(
                channel="text", passed=True,
                suggestion="pass", detail="未命中禁词",
            )

        risk_words = [h["word"] for h in hits]
        categories = set(h["category"] for h in hits)

        # 儿童诱导 → block
        if "child_inducement" in categories:
            return ChannelResult(
                channel="text", passed=False,
                risk_words=risk_words, suggestion="block",
                detail=f"命中儿童诱导词: {risk_words}",
            )

        # 医疗功效 → block
        if "medical_terms" in categories:
            return ChannelResult(
                channel="text", passed=False,
                risk_words=risk_words, suggestion="block",
                detail=f"命中医疗功效词: {risk_words}",
            )

        # 价格欺诈 → block
        if "price_fraud" in categories:
            return ChannelResult(
                channel="text", passed=False,
                risk_words=risk_words, suggestion="block",
                detail=f"命中价格欺诈词: {risk_words}",
            )

        # 其他：绝对化 / 敏感词 → review
        return ChannelResult(
            channel="text", passed=False,
            risk_words=risk_words, suggestion="review",
            detail=f"命中敏感词: {risk_words}",
        )

    # ─── 通道2：ASR 语音检测（预留）──────────────────

    def _check_asr(self, video_path: str) -> ChannelResult:
        """ TODO: Whisper 转写 → 文本检测
        1. ffmpeg 提取音轨: ffmpeg -i video.mp4 -vn -acodec pcm_s16le audio.wav
        2. Whisper 转写: whisper audio.wav --language zh
        3. 对转写结果做禁词扫描
        """
        return ChannelResult(
            channel="asr", passed=True,
            suggestion="pass", detail="ASR 未启用（待接入 Whisper）",
        )

    # ─── 通道3：OCR 画面检测（预留）──────────────────

    def _check_ocr(self, video_path: str) -> ChannelResult:
        """ TODO: DashScope OCR 关键帧 → 文本检测
        1. extract_keyframes(video_path, interval=1.0)
        2. DashScope OCR: RecognizeTextAdvanced
        3. 对识别结果做禁词扫描
        """
        return ChannelResult(
            channel="ocr", passed=True,
            suggestion="pass", detail="OCR 未启用（待接入 DashScope OCR）",
        )

    # ─── 通道4：脚本-配音一致性 ──────────────────────

    def _calculate_similarity(self, script: str, asr_text: str) -> float:
        """文本相似度"""
        if not asr_text:
            return 1.0
        return SequenceMatcher(None, script, asr_text).ratio()

    # ─── 综合风险评估 ──────────────────────────────

    def _assess_risk(self, report: ComplianceReport) -> str:
        score = 0

        for channel_result in [report.text_check, report.asr_check, report.ocr_check]:
            if not channel_result:
                continue
            if channel_result.suggestion == "block":
                score += 40
            elif channel_result.suggestion == "review":
                score += 15
                # 多个违规词叠加风险
                if len(channel_result.risk_words) >= 3:
                    score += 10

        # 脚本-配音偏离
        if report.script_asr_similarity < self.SIMILARITY_THRESHOLD:
            score += 10

        report.total_risk_score = score

        if score >= 50:
            return "high"
        elif score >= 20:
            return "medium"
        return "low"
