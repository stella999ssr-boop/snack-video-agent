"""
第2层 · 模型层 — LLM 能力定义

包含：
  - System Prompt 构建
  - 千川投放标签字典
  - 类目树
"""

from .system_prompt import build_system_prompt
from .tag_dictionary import (
    validate_audience, suggest_audience,
    TAG_DICTIONARY, CATEGORY_TREE, CATEGORY_AUDIENCE_MAP,
)

__all__ = [
    "build_system_prompt",
    "validate_audience",
    "suggest_audience",
    "TAG_DICTIONARY",
    "CATEGORY_TREE",
    "CATEGORY_AUDIENCE_MAP",
]
