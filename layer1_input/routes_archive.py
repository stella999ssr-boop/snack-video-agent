"""
素材档案 API — 浏览、搜索、查看历史素材
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/archive", tags=["素材档案"])

# 由 main.py 注入
_memory = None


def set_memory(memory):
    """由 main.py 调用，注入 MemoryManager 实例"""
    global _memory
    _memory = memory


@router.get("/all")
async def list_all(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    """分页列出所有素材（按创建时间排序）"""
    if _memory is None:
        raise HTTPException(status_code=503, detail="记忆管理器未初始化")

    items = _memory.creatives.list_all(limit=limit, offset=offset)
    return {"total": len(items), "limit": limit, "offset": offset, "items": items}


@router.get("/search")
async def search(
    query: str = Query("", description="搜索关键词/产品名"),
    category: Optional[str] = Query(None),
    script_type: Optional[str] = Query(None),
    n_results: int = Query(10, ge=1, le=50),
):
    """搜索素材（语义检索 + 条件过滤）"""
    if _memory is None:
        raise HTTPException(status_code=503, detail="记忆管理器未初始化")

    results = _memory.creatives.search(
        query=query or "零食",
        n_results=n_results,
        category=category,
        script_type=script_type,
    )
    return {"query": query, "n_results": n_results, "items": results}


@router.get("/categories")
async def get_categories():
    """获取所有类目及其素材数量"""
    if _memory is None:
        raise HTTPException(status_code=503, detail="记忆管理器未初始化")

    return {"categories": _memory.creatives.get_categories()}


@router.get("/{creative_id}")
async def get_creative(creative_id: str):
    """获取单个素材完整详情（含 storyboard 解析）"""
    if _memory is None:
        raise HTTPException(status_code=503, detail="记忆管理器未初始化")

    item = _memory.creatives.get_by_id(creative_id)
    if not item:
        raise HTTPException(status_code=404, detail="素材不存在")

    # 解析 bundle_json 为友好结构
    bundle_json = item.get("bundle_json", "")
    if bundle_json:
        try:
            item["bundle"] = json.loads(bundle_json)
        except json.JSONDecodeError:
            item["bundle"] = None

    # 解析 ad_titles（存储为逗号分隔字符串）
    ad_titles = item.get("ad_titles", "")
    if ad_titles and isinstance(ad_titles, str):
        item["ad_titles"] = [t.strip() for t in ad_titles.split(",") if t.strip()]

    # 解析 suggested_audience
    audience = item.get("suggested_audience", "")
    if audience and isinstance(audience, str):
        try:
            item["suggested_audience"] = json.loads(audience)
        except json.JSONDecodeError:
            pass

    return item
