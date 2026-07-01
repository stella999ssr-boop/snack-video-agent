"""
两写①：writeContextFiles() — 写结构化上下文文件

输出目标：
  1. CLAUDE.md      → marker block 注入项目上下文（给 Agent CLI 读）
  2. AGENTS.md      → marker block 注入 Agent 指令
  3. resources.json → .agent_context/project/resources.json（结构化，给工具/脚本读）
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .task_context import TaskContextForEnv, SkillDef, ProjectResource
from .marker_manager import MarkerManager
from .sidecar_manifest import SidecarManifest


# ─── 默认文件路径 ─────────────────────────────────

def _find_project_root() -> Path:
    """查找项目根目录"""
    # 从当前文件向上找到 snack-ad-agent 目录
    current = Path(__file__).resolve().parent.parent  # context_writer → layer5_context → root
    return current


def write_context_files(
    ctx: TaskContextForEnv,
    *,
    manifest: Optional[SidecarManifest] = None,
) -> dict:
    """
    写结构化上下文文件。

    Args:
        ctx: 聚合后的上下文
        manifest: sidecar manifest（如提供则追踪写入的文件）

    Returns:
        {"files_written": [...], "blocks_injected": [...]}
    """
    root = _find_project_root()
    result = {"files_written": [], "blocks_injected": []}

    # ── 1. CLAUDE.md — 注入项目上下文 ──
    claude_md = root / "CLAUDE.md"
    if claude_md.exists() or True:  # 不存在也创建
        marker = MarkerManager(str(claude_md))
        # 先清理旧块
        marker.cleanup()
        # 注入项目上下文
        project_context = _build_project_context_md(ctx)
        marker.inject("project_context", project_context)
        result["blocks_injected"].append(f"CLAUDE.md:project_context")
        if manifest:
            manifest.track("CLAUDE.md")  # 只追踪我们修改的，但不删除

    # ── 2. AGENTS.md — 注入 Agent 运行时指令 ──
    agents_md = root / "AGENTS.md"
    marker = MarkerManager(str(agents_md))
    marker.cleanup()
    agent_context = _build_agent_context_md(ctx)
    marker.inject("agent_runtime", agent_context)
    result["blocks_injected"].append("AGENTS.md:agent_runtime")
    if manifest:
        manifest.track("AGENTS.md")

    # ── 3. resources.json — 结构化项目资源 ──
    resources_dir = root / ".agent_context" / "project"
    resources_dir.mkdir(parents=True, exist_ok=True)
    resources_path = resources_dir / "resources.json"
    resources_data = _build_resources_json(ctx)
    resources_path.write_text(
        json.dumps(resources_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["files_written"].append(str(resources_path.relative_to(root)))
    if manifest:
        manifest.track(str(resources_path.relative_to(root)))
        manifest.track_dir(str(resources_dir.relative_to(root)))

    return result


# ─── 内容构建函数 ─────────────────────────────────


def _build_project_context_md(ctx: TaskContextForEnv) -> str:
    """构建项目上下文（Markdown 格式，注入到 CLAUDE.md）"""
    lines = [
        "## 项目上下文（Agent 自动注入）",
        "",
        f"- **注入时间**: {ctx.created_at}",
        f"- **会话 ID**: {ctx.session_id}",
        "",
        "### 当前产品",
        f"- 商品名称: {ctx.product_name}",
        f"- 一级类目: {ctx.category_l1}",
        f"- 二级类目: {ctx.category_l2}",
    ]

    if ctx.user_preferences:
        lines.append("\n### 用户偏好")
        for k, v in ctx.user_preferences.items():
            lines.append(f"- {k}: {v}")

    if ctx.top_category_strategies:
        lines.append("\n### 同品类最佳策略")
        for s in ctx.top_category_strategies[:3]:
            lines.append(
                f"- {s.get('script_type', '?')}+{s.get('hook_type', '?')} "
                f"ROI={s.get('avg_roi', 0):.1f} ({s.get('sample_count', 0)}样本)"
            )

    if ctx.project_resources:
        lines.append("\n### 项目资源")
        for r in ctx.project_resources:
            lines.append(f"- [{r.label or r.resource_type}] {r.resource_ref}")

    lines.append(f"\n> 此块由 Agent 自动管理，{ctx.created_at} 写入")
    return "\n".join(lines)


def _build_agent_context_md(ctx: TaskContextForEnv) -> str:
    """构建 Agent 运行时上下文（Markdown 格式，注入到 AGENTS.md）"""
    lines = [
        "## Agent 运行时（自动注入）",
        "",
        "### 可用技能",
    ]
    for skill in ctx.available_skills:
        lines.append(f"- **{skill.name}**: {skill.description}")

    if ctx.taboo_words:
        lines.append(f"\n### 禁忌词\n{', '.join(ctx.taboo_words)}")

    if ctx.strategy_insight:
        lines.append(f"\n### 策略洞察\n{ctx.strategy_insight}")

    lines.append(f"\n> 此块由 Agent 自动管理，{ctx.created_at} 写入")
    return "\n".join(lines)


def _build_resources_json(ctx: TaskContextForEnv) -> dict:
    """构建结构化项目资源 JSON"""
    return {
        "session_id": ctx.session_id,
        "prior_session_id": ctx.prior_session_id,
        "prior_work_dir": ctx.prior_work_dir,
        "user_id": ctx.user_id,
        "product": {
            "name": ctx.product_name,
            "category_l1": ctx.category_l1,
            "category_l2": ctx.category_l2,
        },
        "resources": [
            {
                "id": r.id,
                "resource_type": r.resource_type,
                "resource_ref": r.resource_ref,
                "label": r.label,
            }
            for r in ctx.project_resources
        ],
        "updated_at": ctx.created_at,
    }
