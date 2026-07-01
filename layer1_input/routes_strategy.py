"""
策略效果 API — Top 策略排行、同品类对比、数据洞察
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/strategy", tags=["策略效果"])

# 由 main.py 注入
_memory = None


def set_memory(memory):
    """由 main.py 调用，注入 MemoryManager 实例"""
    global _memory
    _memory = memory


@router.get("/top")
async def get_top_performers(
    category: Optional[str] = Query(None, description="品类筛选"),
    user_id: Optional[str] = Query(None, description="用户ID"),
    limit: int = Query(10, ge=1, le=50),
):
    """获取 ROI 最高的素材策略排行"""
    if _memory is None:
        raise HTTPException(status_code=503, detail="记忆管理器未初始化")

    items = _memory.get_top_performers(category=category, user_id=user_id)
    return {"total": len(items), "items": items}


@router.get("/comparison")
async def get_strategy_comparison(category: str = Query(..., description="品类名称，必填")):
    """同一品类下不同策略的效果对比"""
    if _memory is None:
        raise HTTPException(status_code=503, detail="记忆管理器未初始化")

    items = _memory.get_strategy_comparison(category)
    return {"category": category, "total": len(items), "items": items}


@router.get("/insight")
async def get_strategy_insight(category: str = Query(..., description="品类名称，必填")):
    """获取策略效果的自然语言洞察"""
    if _memory is None:
        raise HTTPException(status_code=503, detail="记忆管理器未初始化")

    insight = _memory.get_strategy_insight(category)
    return {"category": category, "insight": insight}
