"""
第1层 · 用户输入 — FastAPI 路由
接入第2层 Agent，实现完整的请求→生成→查询链路
"""

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from security import safe_error_message
from layer6_execution.state import AgentState, AgentStage
from .schemas import CreativeInput, CreativeInputResponse

router = APIRouter(prefix="/api/v1/creative", tags=["素材生成"])

# Agent 实例由 main.py 注入
_agent = None
# 运行时状态存储: request_id → AgentState
_states: dict = {}


def set_agent(agent):
    """由 main.py 调用，注入 Agent 实例"""
    global _agent
    _agent = agent


def _run_agent(request_id: str, input_data: CreativeInput):
    """后台任务：运行 Agent"""
    state = _states[request_id]
    try:
        product = input_data.model_dump()
        _agent.run(product, session_id=request_id, state=state)
    except Exception as error:
        state.stage = AgentStage.FAILED
        state.error = safe_error_message(error)


@router.get("/categories")
async def get_categories():
    """获取类目树（一级→二级），供前端级联下拉使用"""
    from layer2_model.tag_dictionary import CATEGORY_TREE
    return {"categories": CATEGORY_TREE}


@router.post("/generate", response_model=CreativeInputResponse)
async def create_creative(input_data: CreativeInput, background_tasks: BackgroundTasks):
    """
    提交素材生成请求。

    接收完整的产品信息和素材资源，后台调用 Agent 生成素材方案。
    返回 request_id 用于后续查询状态和结果。
    """
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent 未初始化")

    request_id = str(uuid.uuid4())[:8]
    _states[request_id] = AgentState(
        session_id=request_id,
        product_input=input_data.model_dump(),
    )
    background_tasks.add_task(_run_agent, request_id, input_data)

    return CreativeInputResponse(
        request_id=request_id,
        status="accepted",
        message=f"素材生成请求已接收 [{input_data.product_name}]，排队中...",
        product_name=input_data.product_name,
    )


@router.get("/status/{request_id}")
async def get_status(request_id: str):
    """查询素材生成进度和结果"""
    state = _states.get(request_id)

    if state is None:
        return {
            "request_id": request_id,
            "status": "pending",
            "stage": "waiting",
            "message": "任务排队中或 request_id 不存在",
        }

    if state.stage.value == "failed":
        status = "failed"
    elif state.is_complete:
        status = "done"
    else:
        status = "running"

    response = {
        "request_id": request_id,
        "session_id": state.session_id,
        "status": status,
        "stage": state.stage.value,
        "steps": state.step_count,
        "error": safe_error_message(state.error) if state.error else None,
    }

    # 脚本一经生成就立即返回，视频仍可在后台继续渲染。
    # 只暴露用户需要的创意结果，避免泄露模型 Prompt 等内部字段。
    if state.creative_bundle:
        bundle = state.creative_bundle
        response["script_preview"] = {
            "product_name": bundle.get("product_name"),
            "script_type": bundle.get("script_type"),
            "hook": bundle.get("hook"),
            "storyboard": bundle.get("storyboard"),
            "ad_titles": bundle.get("ad_titles"),
            "creative_rationale": bundle.get("creative_rationale"),
        }

    # 如果已完成，附加完整结果
    if state.is_complete and state.creative_bundle:
        bundle = state.creative_bundle
        response["result"] = {
            "product_name": bundle.get("product_name"),
            "script_type": bundle.get("script_type"),
            "hook": bundle.get("hook"),
            "storyboard": bundle.get("storyboard"),
            "ad_titles": bundle.get("ad_titles"),
            "suggested_audience": bundle.get("suggested_audience"),
            "creative_rationale": bundle.get("creative_rationale"),
        }
        if state.video_url:
            response["result"]["video_url"] = state.video_url
        if state.quality_report:
            response["quality"] = state.quality_report
        if state.compliance_route:
            response["compliance"] = state.compliance_route

    return response


@router.get("/status")
async def list_sessions():
    """列出所有会话状态"""
    return {
        "total": len(_states),
        "sessions": [
            {
                "request_id": rid,
                "stage": s.stage.value,
                "steps": s.step_count,
                "is_complete": s.is_complete,
            }
            for rid, s in _states.items()
        ],
    }


@router.delete("/status/{request_id}")
async def cleanup_session(request_id: str):
    """清理会话状态"""
    if request_id in _states:
        del _states[request_id]
        return {"deleted": request_id}
    raise HTTPException(status_code=404, detail="会话不存在")
