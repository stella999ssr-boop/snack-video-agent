"""
第2层 · Agent 核心 — Controller-Driven Pipeline

流程:
  aggregate_context → write_files → inject_brief → generate → compliance → archive → cleanup

上下文注入采用 Multica 模式：
  一进: TaskContextForEnv 聚合上下文
  两写: writeContextFiles + InjectRuntimeConfig
  两清理: marker block + sidecarManifest
"""

import json
import re
import uuid
from datetime import datetime
from typing import Optional

import httpx

from layer6_execution.state import AgentState, AgentStage, ReActStep
from layer2_model.system_prompt import build_system_prompt
from layer6_execution.tool_registry import ToolRegistry, TOOL_DEFINITIONS
from layer2_model.tag_dictionary import validate_audience, suggest_audience
from layer5_context import (
    TaskContextForEnv,
    write_context_files,
    inject_runtime_config,
    cleanup_marker_blocks,
    SidecarManifest,
)

from layer3_memory.memory_manager import MemoryManager
from layer3_memory.schemas import CreativeRecord
from layer4_tools.tools.wan22 import Wan22Tool, Wan22Result, TaskStatus
from layer4_tools.quality.quality_checker import VideoQualityChecker
from layer4_tools.compliance.review_router import run_compliance_pipeline, ReviewDecision


class CreativeAgent:
    """
    零食投流素材生成 Agent。

    Usage:
        agent = CreativeAgent(
            memory_manager=memory_mgr,
            dashscope_api_key="sk-...",
            user_id="user_001",
        )
        result = agent.run(product_input)
    """

    DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    MODEL = "qwen-plus"

    def __init__(
        self,
        memory_manager: MemoryManager,
        dashscope_api_key: str = "",
        user_id: str = "",
        demo_mode: bool = False,
        enable_video: bool = False,
        context_work_dir: str = "",
    ):
        self.memory = memory_manager
        self.user_id = user_id
        self.demo_mode = demo_mode or not dashscope_api_key
        self.enable_video = enable_video and not self.demo_mode

        # 上下文注入系统
        self.context_work_dir = context_work_dir or ".agent_context"
        self.manifest = SidecarManifest(work_dir=self.context_work_dir)

        # 工具
        self.wan22 = Wan22Tool(api_key=dashscope_api_key)
        self.tools = ToolRegistry(memory=memory_manager, wan22=self.wan22)
        self.quality_checker = VideoQualityChecker(vision_api_key=dashscope_api_key)

        # LLM 客户端
        self._llm_client = httpx.Client(
            base_url="https://dashscope.aliyuncs.com",
            headers={
                "Authorization": f"Bearer {dashscope_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(120),
        ) if not self.demo_mode else None

        # System prompt
        self.system_prompt = build_system_prompt()

    # ═══════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════

    def run(self, product_input: dict, session_id: str = "") -> AgentState:
        """主入口：接收产品输入 → ReAct 循环 → 返回素材方案"""
        state = AgentState(
            session_id=session_id or uuid.uuid4().hex[:8],
            user_id=self.user_id,
            product_input=product_input,
        )

        # 启动会话
        self.memory.start_session(state.session_id)

        try:
            self._react_loop(state)
        except Exception as e:
            state.stage = AgentStage.FAILED
            state.error = str(e)

        return state

    # ═══════════════════════════════════════════
    # ReAct 循环
    # ═══════════════════════════════════════════

    def _react_loop(self, state: AgentState):
        """Controller-Driven Pipeline — 聚合上下文 → 生成 → 质检 → 存档 → 清理"""

        # ── 一进：聚合上下文 ──
        self._current_ctx = TaskContextForEnv.aggregate(
            memory_manager=self.memory,
            product_input=state.product_input,
            session_id=state.session_id,
            user_id=self.user_id,
        )
        state.stage = AgentStage.ANALYZING

        # ── 两写①：写结构化上下文文件 ──
        write_result = write_context_files(self._current_ctx, manifest=self.manifest)
        print(f"[Agent] 上下文文件写入: {write_result}")

        # ── 两写②：生成运行时简报 ──
        brief = inject_runtime_config(self._current_ctx)
        self._current_brief = brief
        print(f"[Agent] 运行时简报已生成, 产品={brief.product_name}")

        # Step 1: 检索记忆库
        state.stage = AgentStage.SEARCHING
        kb_result = self.tools._search_kb(
            query=TaskContextForEnv._build_search_query(state.product_input),
            category=self._current_ctx.category_l2,
        )
        state.add_step(
            thought="检索记忆库，了解同品类历史素材和策略效果",
            action="search_kb",
            action_input={"query": TaskContextForEnv._build_search_query(state.product_input)},
            observation=json.dumps(kb_result, ensure_ascii=False),
        )

        # Step 2: 生成 Creative Bundle
        state.stage = AgentStage.GENERATING
        bundle = self._generate_bundle(state)
        state.creative_bundle = bundle
        state.add_step(
            thought=self._build_creative_thought(state, kb_result),
            action="generate_creative",
            action_input=state.product_input,
            observation=json.dumps(bundle, ensure_ascii=False),
        )

        # 校验人群标签
        audience = bundle.get("suggested_audience", {})
        valid, invalid_tags = validate_audience(audience)
        if not valid:
            # 修正非法标签
            corrected = suggest_audience(
                category=state.product_input.get("category_l2", ""),
                selling_points=state.product_input.get("features", {}).get("selling_points", []),
            )
            bundle["suggested_audience"] = corrected
            bundle["audience_note"] = f"原标签 {invalid_tags} 不在千川标签库内，已自动修正"

        # Step 3: 生成视频（仅在启用视频生成时）
        print(f"[Agent] demo_mode={self.demo_mode}, enable_video={self.enable_video}")
        if not self.demo_mode and self.enable_video:
            print("[Agent] 开始调用 Wan2.2 视频生成...")
            state.stage = AgentStage.RENDERING
            video_result = self._generate_video(bundle)
            if video_result and video_result.task_id:
                state.video_task_id = video_result.task_id
                state.add_step(
                    thought="Wan2.2 视频生成任务已提交，等待完成",
                    action="wan22_t2v",
                    action_input={"prompt": bundle.get("wan22_prompt", ""), "duration": 5},
                    observation=f"task_id={video_result.task_id}, status={video_result.status.value}",
                )

                # 轮询等待
                final = self.wan22.wait(video_result.task_id)
                print(f"[Agent] 视频任务完成, status={final.status.value}, video_url={final.video_url}")
                if final.status == TaskStatus.SUCCEEDED and final.video_url:
                    state.video_url = final.video_url

                    # Step 4: 质量评估
                    state.stage = AgentStage.QUALITY_CHECKING
                    quality = self.quality_checker.evaluate(
                        video_path=final.video_url,
                        original_prompt=bundle.get("wan22_prompt", ""),
                        script=bundle,
                    )
                    state.quality_report = quality.to_dict()
                    state.add_step(
                        thought=f"视频生成完成，质量评分: {quality.total_score}/100 ({quality.grade.value})",
                        action="quality_check",
                        action_input={"video_url": final.video_url},
                        observation=json.dumps(quality.to_dict(), ensure_ascii=False),
                    )

                    # Step 5: 合规检测
                    state.stage = AgentStage.COMPLIANCE_CHECKING
                    route = run_compliance_pipeline(
                        script=json.dumps(bundle, ensure_ascii=False),
                        ad_titles=bundle.get("ad_titles", []),
                        video_path=final.video_url,
                        retry_count=state.retry_count,
                    )
                    state.compliance_route = {
                        "decision": route.decision.value,
                        "reason": route.reason,
                        "notes": route.notes,
                    }
                    state.add_step(
                        thought=f"合规检测完成: {route.decision.value}",
                        action="compliance_check",
                        action_input={"video_url": final.video_url},
                        observation=json.dumps(state.compliance_route, ensure_ascii=False),
                    )

                    # 合规重试逻辑
                    if route.decision == ReviewDecision.AUTO_RETRY and state.can_retry:
                        state.stage = AgentStage.RETRYING
                        state.retry_count += 1
                        # 重新生成 bundle（用合规反馈）
                        return self._react_loop(state)

                    if route.decision == ReviewDecision.MANUAL_REVIEW:
                        state.stage = AgentStage.DONE
                        state.creative_bundle["needs_manual_review"] = True

        # Step 6: 存档素材
        self._archive_to_memory(state)

        # Step 7: 结束会话 → 记忆升级
        self.memory.end_session(state.session_id, self.user_id)

        state.stage = AgentStage.DONE

        # ── 两清理：marker block + sidecar manifest ──
        try:
            cleanup_marker_blocks([
                "CLAUDE.md",
                "AGENTS.md",
            ])
            self.manifest.save()
            print(f"[Agent] 清理完成, 追踪文件数={self.manifest.file_count}")
        except Exception as e:
            print(f"[Agent] 清理失败（非致命）: {e}")

    # ═══════════════════════════════════════════
    # Creative Bundle 生成
    # ═══════════════════════════════════════════

    def _generate_bundle(self, state: AgentState) -> dict:
        """调用 LLM 生成完整的 Creative Bundle"""

        product = state.product_input

        # 构建 user message
        user_message = self._build_user_message(state)

        if self.demo_mode:
            # Demo 模式：返回模拟输出
            return self._demo_generate(product)

        # Live 模式：调用 DashScope
        return self._llm_generate(user_message)

    def _llm_generate(self, user_message: str) -> dict:
        """调用 DashScope LLM 生成 Creative Bundle"""
        print(f"[LLM] 调用 DashScope {self.MODEL}...")

        resp = self._llm_client.post(
            "/compatible-mode/v1/chat/completions",
            json={
                "model": self.MODEL,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            },
        )

        if resp.status_code != 200:
            raise RuntimeError(f"DashScope API 返回 {resp.status_code}: {resp.text[:500]}")

        data = resp.json()

        if "error" in data:
            raise RuntimeError(f"DashScope API 错误: {data['error']}")

        if "choices" not in data or not data["choices"]:
            raise RuntimeError(f"LLM 返回空结果: {json.dumps(data, ensure_ascii=False)[:500]}")

        message = data["choices"][0]["message"]
        content = message.get("content", "")

        # 如果模型返回了 tool_calls 而非 content，尝试从中提取
        if not content and message.get("tool_calls"):
            print("[LLM] 模型返回 tool_calls，尝试提取...")
            for tc in message["tool_calls"]:
                if tc.get("function", {}).get("name") == "generate_creative":
                    content = tc["function"].get("arguments", "")
                    break
            if not content:
                content = json.dumps(
                    message["tool_calls"], ensure_ascii=False
                )

        usage = data.get("usage", {})
        print(f"[LLM] 完成, tokens: {usage.get('total_tokens', '?')}")

        return self._parse_bundle(content)

    def _demo_generate(self, product: dict) -> dict:
        """Demo 模式：基于规则生成素材方案（无需 LLM API）"""
        product_name = product.get("product_name", "零食")
        features = product.get("features", {})
        selling_points = features.get("selling_points", ["美味", "实惠"])
        taste_tags = features.get("taste_tags", ["香"])
        use_scene = features.get("use_scene", ["追剧"])
        price_info = product.get("price", {})
        unit_price = price_info.get("unit_price", 9.9)
        original_price = price_info.get("original_price", unit_price * 4)
        category = product.get("category_l2", "零食")

        # 根据卖点选择创意类型
        if unit_price / max(original_price, 1) < 0.5 and original_price > unit_price * 2:
            script_type = "对比测评"
            hook = f"超市卖{original_price:.0f}，这里只要{unit_price}？"
        elif any("非油炸" in s or "健康" in s or "轻" in s for s in selling_points):
            script_type = "知识科普"
            hook = f"还在吃油炸{category}？试试这个非油炸的"
        elif use_scene:
            script_type = "场景植入"
            hook = f"{use_scene[0]}的时候拆一包这个，太爽了"
        else:
            script_type = "数字清单"
            hook = f"回购3次的{category}，第2款最上头"

        # 构建 Wan2.2 Prompt
        sp_text = "，".join(selling_points[:3])
        taste_text = "，".join(taste_tags)
        wan22_prompt = (
            f"Vertical 9:16 smartphone video, 720p. "
            f"Warm food lighting, handheld slight camera shake. "
            f"Close-up shot of golden crispy {product_name}, "
            f"steam rising, crunchy texture visible. "
            f"Natural color grading, appetizing food cinematography. "
            f"Slow motion bite shot at the end, crumbs falling."
        )

        # 人群定向
        audience = suggest_audience(category, selling_points)

        return {
            "product_name": product_name,
            "script_type": script_type,
            "hook": hook,
            "storyboard": [
                {
                    "time": "0-2s",
                    "scene": f"{'超市货架推镜头' if script_type == '对比测评' else '产品特写'}，价格标签{original_price:.0f}元醒目",
                    "copy": hook,
                    "effect": "推镜头+价格弹出",
                },
                {
                    "time": "2-5s",
                    "scene": f"{product_name}酥脆特写，食材纹理清晰可见",
                    "copy": f"{sp_text}，{taste_text}口感",
                    "effect": "微距慢动作+音效",
                },
                {
                    "time": "5-8s",
                    "scene": f"吃{product_name}的满足表情，自然光手持",
                    "copy": f"{unit_price}元到手，点下方小黄车试试",
                    "effect": "自然过渡到下单引导",
                },
            ],
            "wan22_prompt": wan22_prompt,
            "ad_titles": [
                f"{product_name}，{unit_price}元到手！追剧必备",
                f"还在吃贵的？{product_name}只要{unit_price}，{selling_points[0] if selling_points else '超好吃'}",
                f"{'，'.join(selling_points[:2])}的{category}，{unit_price}元你还要啥自行车",
            ],
            "suggested_audience": audience,
            "creative_rationale": f"{script_type}型，利用{'价格优势' if script_type == '对比测评' else '场景共鸣'}建立购买动机",
        }

    # ═══════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════

    def _build_user_message(self, state: AgentState) -> str:
        """
        构建发送给 LLM 的 user message。

        使用运行时简报（CreativeBrief）替代旧的手动字符串拼接。
        简报包含四层上下文：产品信息 > 策略参考 > 用户偏好 > 会话微调。
        """
        # 如果有运行时简报，用它
        if hasattr(self, "_current_brief") and self._current_brief:
            brief_nl = self._current_brief.to_nl()
        else:
            # 降级：快速生成简报
            ctx = TaskContextForEnv.aggregate(
                memory_manager=self.memory,
                product_input=state.product_input,
                session_id=state.session_id,
                user_id=self.user_id,
            )
            brief = inject_runtime_config(ctx)
            brief_nl = brief.to_nl()
            self._current_brief = brief
            self._current_ctx = ctx

        # 附加上一步操作结果
        steps_text = ""
        if state.steps:
            last_step = state.steps[-1]
            steps_text = f"\n\n## 上一步操作结果\n{last_step.observation}"

        return f"""{brief_nl}
{steps_text}

请基于以上信息，生成一个完整的短视频素材方案（JSON 格式）。"""

    def _build_search_query(self, product: dict) -> str:
        """构建 search_kb 的检索查询（委托给 TaskContextForEnv）"""
        return TaskContextForEnv._build_search_query(product)

    def _build_creative_thought(self, state: AgentState, kb_result: dict) -> str:
        insight = kb_result.get("insight", "")
        similar_count = len(kb_result.get("similar_creatives", []))
        return f"基于记忆检索结果（{similar_count}条相似素材），{insight or '结合产品特点'}确定创意方向"

    def _generate_video(self, bundle: dict) -> Optional[Wan22Result]:
        """调用 Wan2.2 生成视频"""
        prompt = bundle.get("wan22_prompt", "")
        if not prompt:
            print("[Agent] _generate_video: prompt 为空，跳过")
            return None

        try:
            print(f"[Agent] _generate_video: 提交 t2v 任务, prompt={prompt[:80]}...")
            result = self.wan22.t2v(prompt=prompt, duration=5)
            print(f"[Agent] _generate_video: 任务已提交, task_id={result.task_id}")
            return result
        except Exception as e:
            print(f"[Agent] _generate_video: 失败 - {e}")
            return None

    def _parse_bundle(self, content: str) -> dict:
        """从 LLM 输出中解析 Creative Bundle JSON"""
        if not content:
            return {}

        # 尝试提取 JSON 块
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 {...} 块
            brace_match = re.search(r'\{.*\}', content, re.DOTALL)
            if brace_match:
                try:
                    return json.loads(brace_match.group())
                except json.JSONDecodeError:
                    pass

        return {"raw_output": content, "parse_error": True}

    def _archive_to_memory(self, state: AgentState):
        """将生成的素材存档到记忆2"""
        bundle = state.creative_bundle
        if not bundle or bundle.get("parse_error"):
            return

        record = CreativeRecord(
            product_name=bundle.get("product_name", state.product_input.get("product_name", "")),
            category=state.product_input.get("category_l2", ""),
            script_type=bundle.get("script_type", ""),
            hook=bundle.get("hook", ""),
            hook_type=self._infer_hook_type(bundle.get("hook", "")),
            visual_style=self._extract_visual_style(bundle.get("wan22_prompt", "")),
            wan22_prompt=bundle.get("wan22_prompt", ""),
            video_url=state.video_url or "",
            ad_titles=bundle.get("ad_titles", []),
            suggested_audience=json.dumps(bundle.get("suggested_audience", {}), ensure_ascii=False),
            bundle_json=json.dumps(bundle, ensure_ascii=False),
            user_id=self.user_id,
        )

        self.memory.archive_creative(record)

    def _infer_hook_type(self, hook: str) -> str:
        if any(w in hook for w in ["只要", "才", "居然"]):
            return "价格反差"
        if "？" in hook:
            return "好奇心"
        if any(w in hook for w in ["回购", "推荐", "清单"]):
            return "数字清单"
        if any(w in hook for w in ["追剧", "办公室", "宿舍"]):
            return "场景代入"
        return "通用"

    def _extract_visual_style(self, prompt: str) -> str:
        parts = []
        if "warm" in prompt.lower():
            parts.append("暖色调")
        if "cool" in prompt.lower():
            parts.append("冷色调")
        if "handheld" in prompt.lower():
            parts.append("手持感")
        if "close-up" in prompt.lower():
            parts.append("特写")
        if "slow" in prompt.lower():
            parts.append("慢动作")
        return "+".join(parts) if parts else "通用"
