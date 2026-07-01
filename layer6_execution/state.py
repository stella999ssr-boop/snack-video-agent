"""
Agent 状态管理 — ReAct 循环状态 + 会话追踪
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentStage(str, Enum):
    """Agent 当前所处阶段"""
    IDLE = "idle"
    ANALYZING = "analyzing"              # 分析产品信息
    SEARCHING = "searching"              # search_kb 检索记忆
    GENERATING = "generating"            # 生成 Creative Bundle
    RENDERING = "rendering"              # wan22 生成视频
    QUALITY_CHECKING = "quality_checking" # 质量评估
    COMPLIANCE_CHECKING = "compliance_checking"  # 合规检测
    RETRYING = "retrying"                # 触发重试
    DONE = "done"
    FAILED = "failed"


@dataclass
class ReActStep:
    """ReAct 循环中的单步记录"""
    step_number: int
    thought: str                         # LLM 的推理
    action: str                          # 工具名
    action_input: dict                   # 工具参数
    observation: str                     # 工具返回
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentState:
    """Agent 的完整运行时状态"""

    # 会话标识
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    user_id: str = ""

    # 当前阶段
    stage: AgentStage = AgentStage.IDLE

    # 输入
    product_input: dict = field(default_factory=dict)

    # ReAct 循环
    steps: list[ReActStep] = field(default_factory=list)
    max_steps: int = 8

    # 生成结果
    creative_bundle: dict = field(default_factory=dict)
    video_url: Optional[str] = None
    video_task_id: Optional[str] = None

    # 质量 & 合规
    quality_report: Optional[dict] = None
    compliance_route: Optional[dict] = None
    retry_count: int = 0
    max_retries: int = 2

    # 错误
    error: Optional[str] = None

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def is_complete(self) -> bool:
        return self.stage in (AgentStage.DONE, AgentStage.FAILED)

    @property
    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def add_step(self, thought: str, action: str, action_input: dict, observation: str):
        self.steps.append(ReActStep(
            step_number=len(self.steps) + 1,
            thought=thought,
            action=action,
            action_input=action_input,
            observation=observation,
        ))

    def to_summary(self) -> dict:
        """生成状态摘要（用于 API 响应）"""
        return {
            "session_id": self.session_id,
            "stage": self.stage.value,
            "step_count": self.step_count,
            "has_video": self.video_url is not None,
            "quality_grade": self.quality_report.get("grade") if self.quality_report else None,
            "retry_count": self.retry_count,
            "error": self.error,
        }
