"""
第2层 · 大模型层 — Controller-Driven Pipeline + Multica 上下文注入

CreativeAgent: 聚合上下文 → 检索记忆 → 生成素材 → 视频 → 质检 → 合规 → 存档 → 清理
上下文注入: 一进(TaskContextForEnv) 两写(ContextFiles+RuntimeBrief) 两清理(Marker+Sidecar)
"""
from .agent import CreativeAgent
from .state import AgentState, AgentStage, ReActStep
from .tool_registry import ToolRegistry, TOOL_DEFINITIONS
from .tag_dictionary import validate_audience, suggest_audience, TAG_DICTIONARY
from .system_prompt import build_system_prompt
from .context import (
    TaskContextForEnv,
    write_context_files,
    inject_runtime_config,
    CreativeBrief,
    cleanup_marker_blocks,
    SidecarManifest,
)

__all__ = [
    "CreativeAgent",
    "AgentState", "AgentStage", "ReActStep",
    "ToolRegistry", "TOOL_DEFINITIONS",
    "validate_audience", "suggest_audience", "TAG_DICTIONARY",
    "build_system_prompt",
    "TaskContextForEnv",
    "write_context_files",
    "inject_runtime_config",
    "CreativeBrief",
    "cleanup_marker_blocks",
    "SidecarManifest",
]
