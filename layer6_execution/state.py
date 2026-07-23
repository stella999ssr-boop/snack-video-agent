"""
Agent 状态管理 — ReAct 循环状态 + 会话追踪
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


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
    INTERRUPTED = "interrupted"          # 服务重启，本地处理已中断
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
    video_path: Optional[str] = None
    video_task_id: Optional[str] = None
    video_tasks: list[dict] = field(default_factory=list)
    video_stage: str = ""
    progress_message: str = ""

    # 质量 & 合规
    quality_report: Optional[dict] = None
    compliance_route: Optional[dict] = None
    retry_count: int = 0
    max_retries: int = 2

    # 错误
    error: Optional[str] = None
    updated_at: float = field(default_factory=time.time)

    # 路由层注入的持久化回调，不写入数据库。
    _checkpoint_callback: Optional[Callable[["AgentState"], None]] = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def is_complete(self) -> bool:
        return self.stage in (
            AgentStage.DONE,
            AgentStage.FAILED,
            AgentStage.INTERRUPTED,
        )

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
        self.checkpoint()

    def set_checkpoint_callback(self, callback: Callable[["AgentState"], None]):
        """注入状态落盘函数。"""
        self._checkpoint_callback = callback

    def checkpoint(self):
        """刷新时间并立即持久化当前状态。"""
        self.updated_at = time.time()
        if self._checkpoint_callback:
            self._checkpoint_callback(self)

    def set_stage(self, stage: AgentStage, message: str = ""):
        self.stage = stage
        if message:
            self.progress_message = message
        self.checkpoint()

    def set_error(self, message: str):
        self.error = message
        self.set_stage(AgentStage.FAILED, message)

    def set_video_stage(self, stage: str, message: str):
        self.video_stage = stage
        self.progress_message = message
        self.checkpoint()

    def record_video_task(self, shot: int, label: str, task_id: str):
        """task_id 返回后立刻记录，避免进程重启后丢失。"""
        task = next(
            (item for item in self.video_tasks if item.get("shot") == shot),
            None,
        )
        if task is None:
            task = {
                "shot": shot,
                "label": label,
                "task_id": task_id,
                "status": "PENDING",
                "error": None,
            }
            self.video_tasks.append(task)
        else:
            task.update(task_id=task_id, status="PENDING", error=None)
        self.video_task_id = task_id
        self.checkpoint()

    def update_video_task(
        self,
        task_id: str,
        status: str,
        error: Optional[str] = None,
    ):
        task = next(
            (item for item in self.video_tasks if item.get("task_id") == task_id),
            None,
        )
        if task:
            task["status"] = status
            task["error"] = error
            self.checkpoint()

    def to_persisted_dict(self) -> dict:
        """转换为仅含 JSON 安全字段的持久化结构。"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "stage": self.stage.value,
            "product_input": self.product_input,
            "steps": [
                {
                    "step_number": step.step_number,
                    "thought": step.thought,
                    "action": step.action,
                    "action_input": step.action_input,
                    "observation": step.observation,
                    "timestamp": step.timestamp,
                }
                for step in self.steps
            ],
            "max_steps": self.max_steps,
            "creative_bundle": self.creative_bundle,
            "video_url": self.video_url,
            "video_path": self.video_path,
            "video_task_id": self.video_task_id,
            "video_tasks": self.video_tasks,
            "video_stage": self.video_stage,
            "progress_message": self.progress_message,
            "quality_report": self.quality_report,
            "compliance_route": self.compliance_route,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error": self.error,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_persisted_dict(cls, data: dict) -> "AgentState":
        """从 SQLite 中恢复任务状态。"""
        stage_value = data.get("stage", AgentStage.IDLE.value)
        try:
            stage = AgentStage(stage_value)
        except ValueError:
            stage = AgentStage.IDLE
        steps = [
            ReActStep(
                step_number=item.get("step_number", index + 1),
                thought=item.get("thought", ""),
                action=item.get("action", ""),
                action_input=item.get("action_input") or {},
                observation=item.get("observation", ""),
                timestamp=item.get("timestamp", time.time()),
            )
            for index, item in enumerate(data.get("steps") or [])
        ]
        return cls(
            session_id=data.get("session_id") or uuid.uuid4().hex[:8],
            user_id=data.get("user_id", ""),
            stage=stage,
            product_input=data.get("product_input") or {},
            steps=steps,
            max_steps=data.get("max_steps", 8),
            creative_bundle=data.get("creative_bundle") or {},
            video_url=data.get("video_url"),
            video_path=data.get("video_path"),
            video_task_id=data.get("video_task_id"),
            video_tasks=data.get("video_tasks") or [],
            video_stage=data.get("video_stage", ""),
            progress_message=data.get("progress_message", ""),
            quality_report=data.get("quality_report"),
            compliance_route=data.get("compliance_route"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
            error=data.get("error"),
            updated_at=data.get("updated_at", time.time()),
        )

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
            "video_stage": self.video_stage,
            "video_tasks": self.video_tasks,
            "updated_at": self.updated_at,
        }
