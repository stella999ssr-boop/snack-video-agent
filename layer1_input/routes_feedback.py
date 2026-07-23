"""
反馈关联 API — 素材↔广告关联、效果数据查询
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from security import safe_error_message

router = APIRouter(prefix="/api/v1/feedback", tags=["效果反馈"])

# 由 main.py 注入
_linker = None
_collector = None
_writer = None
_memory = None


def set_deps(linker, collector, writer, memory):
    """由 main.py 调用，注入反馈组件"""
    global _linker, _collector, _writer, _memory
    _linker = linker
    _collector = collector
    _writer = writer
    _memory = memory


# ─── 请求模型 ─────────────────────────────────


class LinkRequest(BaseModel):
    creative_id: str = Field(..., description="素材 ID")
    ad_id: str = Field(..., description="千川广告 ID")
    advertiser_id: str = Field(..., description="千川广告主 ID")
    user_id: str = Field(default="demo_user")


class LinkDeleteRequest(BaseModel):
    creative_id: str
    ad_id: str


# ─── 关联操作 ─────────────────────────────────


@router.post("/link")
async def create_link(req: LinkRequest):
    """创建素材↔广告关联"""
    if _linker is None:
        raise HTTPException(status_code=503, detail="关联器未初始化")

    try:
        link = _linker.link(
            user_id=req.user_id,
            creative_id=req.creative_id,
            ad_id=req.ad_id,
            advertiser_id=req.advertiser_id,
        )
        return {"status": "linked", "data": link.__dict__ if hasattr(link, "__dict__") else str(link)}
    except Exception as error:
        raise HTTPException(status_code=500, detail=safe_error_message(error))


@router.delete("/link")
async def delete_link(req: LinkDeleteRequest):
    """取消素材↔广告关联"""
    if _linker is None:
        raise HTTPException(status_code=503, detail="关联器未初始化")

    try:
        _linker.unlink(creative_id=req.creative_id, ad_id=req.ad_id)
        return {"status": "unlinked", "creative_id": req.creative_id, "ad_id": req.ad_id}
    except Exception as error:
        raise HTTPException(status_code=500, detail=safe_error_message(error))


@router.get("/links")
async def list_links(
    user_id: str = Query(default="demo_user"),
    creative_id: Optional[str] = Query(None),
):
    """查询关联列表"""
    if _linker is None:
        raise HTTPException(status_code=503, detail="关联器未初始化")

    if creative_id:
        items = _linker.get_by_creative(creative_id)
    else:
        items = _linker.list_by_user(user_id)

    # 为每个关联附加素材名称
    enriched = []
    for item in items:
        cid = item.get("creative_id", "")
        if _memory:
            creative = _memory.creatives.get_by_id(cid)
            if creative:
                item["product_name"] = creative.get("product_name", "")
                item["category"] = creative.get("category", "")
                item["script_type"] = creative.get("script_type", "")
                item["performance_star"] = creative.get("performance_star", 0)
        enriched.append(item)

    return {"total": len(enriched), "items": enriched}


# ─── 效果数据 ─────────────────────────────────


@router.get("/performance/{creative_id}")
async def get_performance(
    creative_id: str,
    ad_id: Optional[str] = Query(None),
):
    """获取每日效果数据"""
    if _collector is None:
        raise HTTPException(status_code=503, detail="采集器未初始化")

    rows = _collector.get_performance(creative_id=creative_id, ad_id=ad_id or "")
    return {"creative_id": creative_id, "ad_id": ad_id, "days": len(rows), "data": rows}


@router.get("/summary/{creative_id}")
async def get_summary(
    creative_id: str,
    ad_id: str = Query(..., description="广告 ID，必填"),
):
    """获取效果汇总指标"""
    if _collector is None:
        raise HTTPException(status_code=503, detail="采集器未初始化")

    summary = _collector.get_summary(creative_id=creative_id, ad_id=ad_id)
    if not summary:
        return {"creative_id": creative_id, "ad_id": ad_id, "data": None, "message": "暂无效果数据"}

    # 计算星级
    roi = summary.get("avg_roi", 0) or 0
    if roi >= 5.0:
        star = 5
    elif roi >= 3.0:
        star = 4
    elif roi >= 1.5:
        star = 3
    elif roi >= 1.0:
        star = 2
    else:
        star = 1

    summary["performance_star"] = star
    return {"creative_id": creative_id, "ad_id": ad_id, "data": summary}
