"""
记忆3：多轮交互微调记忆
Agent State 会话内生效，会话结束即清。
同类型微调 ≥3 次自动升级为记忆1（用户偏好）。
"""

from collections import Counter
from datetime import datetime
from typing import Optional

from .schemas import SessionFeedback
from .user_preferences import UserPreferenceStore


class SessionFeedbackStore:
    """会话内微调记录，纯内存存储"""

    # 升级阈值：同类型微调 ≥ N 次 → 自动写入用户偏好
    PROMOTE_THRESHOLD = 3

    def __init__(self, preference_store: UserPreferenceStore):
        self._sessions: dict[str, list[SessionFeedback]] = {}
        self._prefs = preference_store

    # ─── 会话内操作 ─────────────────────────────────

    def record(
        self,
        session_id: str,
        user_feedback: str,
        adjustment_type: str,
        adjusted_field: str,
        adjusted_from: str,
        adjusted_to: str,
    ) -> SessionFeedback:
        """记录一条微调"""
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        fb = SessionFeedback(
            round_number=len(self._sessions[session_id]) + 1,
            user_feedback=user_feedback,
            adjustment_type=adjustment_type,
            adjusted_field=adjusted_field,
            adjusted_from=adjusted_from,
            adjusted_to=adjusted_to,
        )
        self._sessions[session_id].append(fb)
        return fb

    def get_history(self, session_id: str) -> list[SessionFeedback]:
        """获取当前会话全部微调记录"""
        return self._sessions.get(session_id, [])

    def format_for_prompt(self, session_id: str) -> str:
        """格式化为注入 LLM prompt 的文本"""
        history = self.get_history(session_id)
        if not history:
            return ""

        lines = ["\n前几轮微调记录（请基于此调整生成）:"]
        for fb in history:
            lines.append(
                f"  Round {fb.round_number}: {fb.user_feedback} "
                f"→ 已调整 {fb.adjusted_field} ({fb.adjusted_from} → {fb.adjusted_to})"
            )
        return "\n".join(lines)

    def get_adjustment_counts(self, session_id: str) -> Counter:
        """统计各类调整的频次"""
        types = [fb.adjustment_type for fb in self.get_history(session_id)]
        return Counter(types)

    # ─── 升级到记忆1 ─────────────────────────────────

    def promote_to_preferences(self, session_id: str, user_id: str) -> list[str]:
        """
        会话结束时调用。
        同类型微调 ≥ PROMOTE_THRESHOLD 次 → 写入用户偏好。
        返回升级了的偏好类型列表。
        """
        counts = self.get_adjustment_counts(session_id)
        promoted = []

        for adj_type, count in counts.items():
            if count >= self.PROMOTE_THRESHOLD:
                # 提取该类型最后一次微调的结果值
                last_fb = self._last_of_type(session_id, adj_type)
                if last_fb:
                    key = f"prefer_{adj_type}"
                    self._prefs.upsert_from_session(
                        user_id=user_id,
                        key=key,
                        value=last_fb.adjusted_to,
                    )
                    promoted.append(adj_type)

        return promoted

    # ─── 会话生命周期 ─────────────────────────────────

    def start_session(self, session_id: str):
        """初始化新会话"""
        self._sessions[session_id] = []

    def end_session(self, session_id: str, user_id: str) -> list[str]:
        """结束会话 → 尝试升级 → 清理"""
        promoted = self.promote_to_preferences(session_id, user_id)
        self._sessions.pop(session_id, None)
        return promoted

    # ─── 工具方法 ─────────────────────────────────

    def _last_of_type(self, session_id: str, adj_type: str) -> Optional[SessionFeedback]:
        for fb in reversed(self.get_history(session_id)):
            if fb.adjustment_type == adj_type:
                return fb
        return None

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)
