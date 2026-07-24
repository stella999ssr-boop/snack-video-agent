"""
第1层 · 用户输入 — FastAPI 路由
接入第2层 Agent，实现完整的请求→生成→查询链路
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from config import settings
from security import safe_error_message
from layer6_execution.state import AgentState, AgentStage
from .schemas import CreativeInput, CreativeInputResponse
from .task_store import TaskStateStore

router = APIRouter(prefix="/api/v1/creative", tags=["素材生成"])

# Agent 实例由 main.py 注入
_agent = None
# 运行时状态缓存 + SQLite 持久化。
_states: dict = {}
_store = TaskStateStore(settings.SQLITE_PATH)
_recovery_in_progress: set[str] = set()


def _save_state(state: AgentState):
    _states[state.session_id] = state
    _store.save(state)


def _attach_state(state: AgentState) -> AgentState:
    state.set_checkpoint_callback(_save_state)
    _states[state.session_id] = state
    return state


def _repair_fake_video_completion(state: AgentState):
    """将旧版遗留的 live/DONE/无视频状态纠正为失败，避免继续显示 100%。"""
    if (
        _agent is not None
        and not _agent.demo_mode
        and state.stage == AgentStage.DONE
        and not state.video_url
    ):
        message = (
            "脚本已生成，但没有生成可播放的视频成片；"
            "该任务已从错误的完成状态纠正为视频未生成。"
        )
        state.error = message
        state.video_stage = "delivery_failed"
        state.set_stage(AgentStage.FAILED, message)


def set_agent(agent):
    """由 main.py 调用，注入 Agent 并恢复历史任务状态。"""
    global _agent
    _agent = agent
    for state in _store.list_all():
        _attach_state(state)
        _repair_fake_video_completion(state)
        if not state.is_complete:
            task_count = len(state.video_tasks)
            if task_count:
                message = (
                    f"服务重启中断了本地处理；已保留 {task_count} 个 "
                    "Wan2.2 任务编号，不会自动重复提交"
                )
            else:
                message = (
                    "服务重启发生在 Wan2.2 返回任务编号之前；"
                    "没有已确认的视频任务"
                )
            state.error = message
            state.video_stage = "interrupted"
            state.set_stage(AgentStage.INTERRUPTED, message)


def _run_agent(request_id: str, input_data: CreativeInput):
    """后台任务：运行 Agent"""
    state = _states[request_id]
    try:
        product = input_data.model_dump()
        _agent.run(product, session_id=request_id, state=state)
    except Exception as error:
        state.set_error(safe_error_message(error))


def _is_video_recoverable(state: AgentState) -> bool:
    task_ids = {
        task.get("shot"): task.get("task_id")
        for task in state.video_tasks
        if task.get("shot") in (1, 2) and task.get("task_id")
    }
    return (
        state.stage in (AgentStage.FAILED, AgentStage.INTERRUPTED)
        and not state.video_url
        and bool(state.creative_bundle)
        and len(task_ids) == 2
    )


def _latest_recoverable_state() -> AgentState | None:
    for persisted_state in _store.list_all():
        if persisted_state.session_id not in _states:
            _attach_state(persisted_state)
    candidates = [
        state for state in _states.values()
        if _is_video_recoverable(state)
    ]
    return max(candidates, key=lambda state: state.updated_at, default=None)


def _run_video_recovery(request_id: str):
    """后台复用已保存 task_id 合成视频；此路径不会调用 Wan i2v/t2v。"""
    state = _states[request_id]
    try:
        _agent.recover_video_from_existing_tasks(state)
    except Exception as error:
        state.set_error(safe_error_message(error))
    finally:
        _recovery_in_progress.discard(request_id)


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
    state = _attach_state(AgentState(
        session_id=request_id,
        product_input=input_data.model_dump(),
        progress_message="任务已接收，准备分析商品信息",
    ))
    state.checkpoint()
    background_tasks.add_task(_run_agent, request_id, input_data)

    return CreativeInputResponse(
        request_id=request_id,
        status="accepted",
        message=f"素材生成请求已接收 [{input_data.product_name}]，排队中...",
        product_name=input_data.product_name,
    )


@router.get("/recovery/latest")
async def get_latest_recoverable_video():
    """返回最近一个可复用两个 Wan2.2 task_id 的失败任务。"""
    state = _latest_recoverable_state()
    if state is None:
        return {"recoverable": False}
    return {
        "recoverable": True,
        "request_id": state.session_id,
        "updated_at": state.updated_at,
        "task_count": len(state.video_tasks),
        "in_progress": state.session_id in _recovery_in_progress,
    }


@router.post("/recovery/latest")
async def recover_latest_video(background_tasks: BackgroundTasks):
    """
    复用最近失败任务的两个 task_id 重新合成。

    该入口只查询既有任务并下载结果，不会提交新的 Wan2.2 生成任务。
    """
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent 未初始化")
    state = _latest_recoverable_state()
    if state is None:
        raise HTTPException(
            status_code=404,
            detail="没有找到同时保存了两个 Wan2.2 task_id 的可恢复任务",
        )
    if state.session_id in _recovery_in_progress:
        return {
            "request_id": state.session_id,
            "status": "running",
            "message": "现有片段正在恢复合成，请勿重复操作",
        }

    _recovery_in_progress.add(state.session_id)
    background_tasks.add_task(_run_video_recovery, state.session_id)
    return {
        "request_id": state.session_id,
        "status": "accepted",
        "message": "已开始复用现有 Wan2.2 任务；不会重新提交视频生成",
    }


@router.get("/status/{request_id}")
async def get_status(request_id: str):
    """查询素材生成进度和结果"""
    state = _states.get(request_id)
    if state is None:
        state = _store.get(request_id)
        if state:
            _attach_state(state)

    if state is None:
        return {
            "request_id": request_id,
            "status": "pending",
            "stage": "waiting",
            "message": "任务排队中或 request_id 不存在",
        }

    _repair_fake_video_completion(state)

    if state.stage == AgentStage.FAILED:
        status = "failed"
    elif state.stage == AgentStage.INTERRUPTED:
        status = "interrupted"
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
        "message": state.progress_message or None,
        "updated_at": state.updated_at,
        "video_recoverable": _is_video_recoverable(state),
        "video_progress": {
            "stage": state.video_stage,
            "message": state.progress_message or None,
            "tasks": [
                {
                    "shot": task.get("shot"),
                    "label": task.get("label"),
                    "task_id": task.get("task_id"),
                    "status": task.get("status"),
                    "error": safe_error_message(task.get("error"))
                    if task.get("error")
                    else None,
                }
                for task in state.video_tasks
            ],
        },
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

    # 只有真实成功才返回完整结果；失败/中断时仍保留上方脚本预览。
    if state.stage == AgentStage.DONE and state.creative_bundle:
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
    for persisted_state in _store.list_all():
        if persisted_state.session_id not in _states:
            _attach_state(persisted_state)
    return {
        "total": len(_states),
        "sessions": [
            {
                "request_id": rid,
                "stage": s.stage.value,
                "steps": s.step_count,
                "is_complete": s.is_complete,
                "video_stage": s.video_stage,
                "video_tasks": len(s.video_tasks),
            }
            for rid, s in _states.items()
        ],
    }


@router.delete("/status/{request_id}")
async def cleanup_session(request_id: str):
    """清理会话状态"""
    deleted_from_memory = _states.pop(request_id, None) is not None
    deleted_from_store = _store.delete(request_id)
    if deleted_from_memory or deleted_from_store:
        return {"deleted": request_id}
    raise HTTPException(status_code=404, detail="会话不存在")
