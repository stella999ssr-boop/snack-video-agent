"""
第5层 · 上下文层 — Multica 模式上下文注入

一进: TaskContextForEnv 聚合上下文
两写: writeContextFiles + InjectRuntimeConfig
两清理: marker block + sidecarManifest
"""

from .task_context import TaskContextForEnv, SkillDef, ProjectResource
from .context_writer import write_context_files
from .runtime_brief import inject_runtime_config, CreativeBrief
from .marker_manager import MarkerManager, cleanup_marker_blocks
from .sidecar_manifest import SidecarManifest

__all__ = [
    "TaskContextForEnv",
    "SkillDef",
    "ProjectResource",
    "write_context_files",
    "inject_runtime_config",
    "CreativeBrief",
    "MarkerManager",
    "cleanup_marker_blocks",
    "SidecarManifest",
]
