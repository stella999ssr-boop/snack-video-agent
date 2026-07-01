"""
工具注册表 — Agent 可调用的 3 个工具

  search_kb:  检索记忆库（历史素材 + 策略效果）
  wan22_t2v:  文生视频
  wan22_i2v:  图生视频

工具定义遵循 DashScope Function Calling 格式。
"""

import json
from typing import Optional

from layer3_memory.memory_manager import MemoryManager
from layer4_tools.tools.wan22 import Wan22Tool


# ═══════════════════════════════════════════════════
# DashScope Function Calling 工具定义
# ═══════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "检索记忆库：查找同品类历史素材方案和策略效果数据。在生成创意之前必须先调用此工具了解历史数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索查询文本，如 '膨化食品 薯条 麻辣 酥脆'",
                    },
                    "category": {
                        "type": "string",
                        "description": "品类筛选项，如 '膨化食品'。不传则不过滤品类。",
                    },
                    "search_type": {
                        "type": "string",
                        "enum": ["history", "strategy", "auto"],
                        "description": "检索类型: history=历史素材, strategy=策略效果, auto=综合检索(默认)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wan22_t2v",
            "description": "调用通义万相 Wan2.2 文生视频模型生成短视频。传入英文 Prompt，返回任务 ID。生成完成后自动触发质量评估和合规检测。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "英文视频描述 Prompt，包含画面内容、运镜方式、色调风格、分辨率。例如: 'Warm lighting, handheld close-up shot of golden crispy potato chips...'",
                    },
                    "duration": {
                        "type": "integer",
                        "enum": [5, 8, 10],
                        "description": "视频时长（秒），默认 5",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["720p", "1080p"],
                        "description": "分辨率，默认 720p",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wan22_i2v",
            "description": "调用通义万相 Wan2.2 图生视频模型。以产品图片作为首帧生成视频。有产品图时优先使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {
                        "type": "string",
                        "description": "产品图片 URL，用作视频首帧",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "英文视频描述 Prompt（画面如何动起来）",
                    },
                    "duration": {
                        "type": "integer",
                        "enum": [5, 8, 10],
                        "description": "视频时长（秒），默认 5",
                    },
                },
                "required": ["image_url", "prompt"],
            },
        },
    },
]


class ToolRegistry:
    """
    工具注册表 — 管理工具定义和执行。

    用法:
        registry = ToolRegistry(memory_manager, wan22_tool)
        result = registry.execute("search_kb", {"query": "薯条 麻辣"})
    """

    def __init__(self, memory: MemoryManager, wan22: Wan22Tool):
        self.memory = memory
        self.wan22 = wan22
        self._tools = {
            "search_kb": self._search_kb,
            "wan22_t2v": self._wan22_t2v,
            "wan22_i2v": self._wan22_i2v,
        }

    @property
    def definitions(self) -> list[dict]:
        return TOOL_DEFINITIONS

    def execute(self, tool_name: str, arguments: dict) -> str:
        """执行工具调用，返回 JSON 字符串"""
        handler = self._tools.get(tool_name)
        if handler is None:
            return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

        try:
            result = handler(**arguments)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ─── 工具实现 ─────────────────────────────────

    def _search_kb(
        self,
        query: str,
        category: Optional[str] = None,
        search_type: str = "auto",
    ) -> dict:
        """检索记忆库"""
        kb_result = self.memory.search_kb(query=query, category=category)

        output = {
            "similar_creatives": [],
            "strategy_effects": [],
            "insight": kb_result.insight,
        }

        # 格式化历史素材
        for c in kb_result.similar_creatives[:5]:
            item = {
                "product_name": c.get("product_name", ""),
                "script_type": c.get("script_type", ""),
                "hook": c.get("hook", ""),
                "hook_type": c.get("hook_type", ""),
                "similarity": c.get("similarity", 0),
            }
            if c.get("has_performance_data"):
                item["performance"] = {
                    "roi": c.get("roi", 0),
                    "star": c.get("performance_star", 0),
                }
            output["similar_creatives"].append(item)

        # 格式化策略效果
        for s in kb_result.strategy_effects[:5]:
            output["strategy_effects"].append({
                "category": s.get("category", ""),
                "script_type": s.get("script_type", ""),
                "hook_type": s.get("hook_type", ""),
                "ctr": s.get("ctr", 0),
                "roi": s.get("roi", 0),
                "similarity": s.get("similarity", 1.0),
            })

        return output

    def _wan22_t2v(
        self,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
    ) -> dict:
        """文生视频"""
        result = self.wan22.t2v(
            prompt=prompt,
            duration=duration,
            resolution=resolution,
        )
        return {
            "task_id": result.task_id,
            "status": result.status.value,
            "message": f"视频生成任务已提交，task_id={result.task_id}",
        }

    def _wan22_i2v(
        self,
        image_url: str,
        prompt: str,
        duration: int = 5,
    ) -> dict:
        """图生视频"""
        result = self.wan22.i2v(
            image_url=image_url,
            prompt=prompt,
            duration=duration,
        )
        return {
            "task_id": result.task_id,
            "status": result.status.value,
            "message": f"图生视频任务已提交，task_id={result.task_id}",
        }
