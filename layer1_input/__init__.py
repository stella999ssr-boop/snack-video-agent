"""
第1层 · 用户输入 — 模块导出
"""

from .schemas import CreativeInput, CreativeInputResponse, PriceInfo, ProductFeatures, ProductAssets
from .routes import router
from .routes_archive import router as archive_router
from .routes_strategy import router as strategy_router
from .routes_feedback import router as feedback_router

__all__ = [
    "CreativeInput",
    "CreativeInputResponse",
    "PriceInfo",
    "ProductFeatures",
    "ProductAssets",
    "router",
    "archive_router",
    "strategy_router",
    "feedback_router",
]
