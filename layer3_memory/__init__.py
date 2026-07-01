"""
第3层 · 记忆层 — 四维记忆体系

记忆1: 用户偏好 (SQLite)
记忆2: 历史素材 (ChromaDB)
记忆3: 会话微调 (Agent State)
记忆4: 策略效果联动 (SQLite + ChromaDB)
"""

from .memory_manager import MemoryManager, create_memory_manager
from .schemas import (
    UserPreference,
    CreativeRecord,
    SessionFeedback,
    StrategyEffect,
    SearchResult,
)

__all__ = [
    "MemoryManager",
    "create_memory_manager",
    "UserPreference",
    "CreativeRecord",
    "SessionFeedback",
    "StrategyEffect",
    "SearchResult",
]
