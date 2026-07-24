"""
第2层 · Agent 核心 — Controller-Driven Pipeline

流程:
  aggregate_context → write_files → inject_brief → generate → compliance → archive → cleanup

上下文注入采用 Multica 模式：
  一进: TaskContextForEnv 聚合上下文
  两写: writeContextFiles + InjectRuntimeConfig
  两清理: marker block + sidecarManifest
"""

import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime

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
from security import safe_error_message


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
    FFMPEG_ASPECT_RATIO_MODE = "decrease"

    def __init__(
        self,
        memory_manager: MemoryManager,
        dashscope_api_key: str = "",
        user_id: str = "",
        demo_mode: bool = False,
        enable_video: bool = False,
        context_work_dir: str = "",
        upload_dir: str = "./static/uploads",
        output_dir: str = "./static/outputs",
    ):
        dashscope_api_key = (dashscope_api_key or "").strip()
        requested_demo_mode = bool(demo_mode)
        if not requested_demo_mode and not dashscope_api_key:
            raise RuntimeError(
                "AGENT_MODE=live 时必须配置 DASHSCOPE_API_KEY，"
                "服务不会静默退回 Demo 模式"
            )
        self.memory = memory_manager
        self.user_id = user_id
        self.demo_mode = requested_demo_mode
        self.enable_video = enable_video and not self.demo_mode
        self.upload_dir = os.path.abspath(upload_dir)
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.upload_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

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

    def run(
        self,
        product_input: dict,
        session_id: str = "",
        state: AgentState = None,
    ) -> AgentState:
        """主入口：接收产品输入 → ReAct 循环 → 返回素材方案"""
        if state is None:
            state = AgentState(
                session_id=session_id or uuid.uuid4().hex[:8],
                user_id=self.user_id,
                product_input=product_input,
            )
        else:
            state.session_id = session_id or state.session_id
            state.user_id = self.user_id
            state.product_input = product_input

        # 启动会话
        self.memory.start_session(state.session_id)

        try:
            self._react_loop(state)
        except Exception as error:
            safe_error = safe_error_message(error)
            state.set_error(safe_error)
            print(f"[Agent] 任务失败: {safe_error}")

        return state

    # ═══════════════════════════════════════════
    # ReAct 循环
    # ═══════════════════════════════════════════

    def _react_loop(self, state: AgentState):
        """Controller-Driven Pipeline — 聚合上下文 → 生成 → 质检 → 存档 → 清理"""

        # ── 一进：聚合上下文 ──
        state.set_stage(AgentStage.ANALYZING, "正在理解商品信息与核心卖点")
        self._current_ctx = TaskContextForEnv.aggregate(
            memory_manager=self.memory,
            product_input=state.product_input,
            session_id=state.session_id,
            user_id=self.user_id,
        )

        # ── 两写①：写结构化上下文文件 ──
        write_result = write_context_files(self._current_ctx, manifest=self.manifest)
        print(f"[Agent] 上下文文件写入: {write_result}")

        # ── 两写②：生成运行时简报 ──
        brief = inject_runtime_config(self._current_ctx)
        self._current_brief = brief
        print(f"[Agent] 运行时简报已生成, 产品={brief.product_name}")

        # Step 1: 检索记忆库
        state.set_stage(AgentStage.SEARCHING, "正在检索同品类历史素材与策略")
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
        state.set_stage(AgentStage.GENERATING, "正在生成 10 秒双镜脚本")
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

        # Step 3: 生成视频。Live 请求必须交付真实成片，不能静默跳过。
        print(f"[Agent] demo_mode={self.demo_mode}, enable_video={self.enable_video}")
        self._require_video_enabled(state)
        if not self.demo_mode:
            state.set_stage(
                AgentStage.RENDERING,
                "脚本已生成，正在准备提交第 1 段 Wan2.2",
            )
            state.set_video_stage(
                "preparing",
                "脚本已生成，正在校验商品主图与双镜视频参数",
            )
            print("[Agent] 启动 10 秒真实图生视频：2 段 × 5 秒...")
            video_url, video_path = self._generate_10s_video(bundle, state)

            state.video_url = video_url or None
            state.video_path = video_path or None
            state.checkpoint()
            self._require_video_delivery(state)

            # Step 4: 质量评估
            state.set_stage(
                AgentStage.QUALITY_CHECKING,
                "视频已生成，正在完成质量评估",
            )
            quality = self.quality_checker.evaluate(
                video_path=video_path,
                original_prompt=bundle.get("wan22_prompt", ""),
                script=bundle,
            )
            state.quality_report = quality.to_dict()
            state.add_step(
                thought=f"视频生成完成，质量评分: {quality.total_score}/100 ({quality.grade.value})",
                action="quality_check",
                action_input={"video_url": video_url},
                observation=json.dumps(quality.to_dict(), ensure_ascii=False),
            )

            # Step 5: 合规检测
            state.set_stage(
                AgentStage.COMPLIANCE_CHECKING,
                "质量评估完成，正在进行广告合规检查",
            )
            route = run_compliance_pipeline(
                script=json.dumps(bundle, ensure_ascii=False),
                ad_titles=bundle.get("ad_titles", []),
                video_path=video_path,
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
                action_input={"video_url": video_url},
                observation=json.dumps(state.compliance_route, ensure_ascii=False),
            )

            # 视频调用会产生费用；检测到问题时保留本次成片并标记复核，
            # 不自动再次生成两段视频，避免一次点击产生多轮费用。
            if route.decision in (
                ReviewDecision.AUTO_RETRY,
                ReviewDecision.MANUAL_REVIEW,
            ):
                state.creative_bundle["needs_manual_review"] = True
                state.checkpoint()

        # Step 6: 存档素材
        self._archive_to_memory(state)

        # Step 7: 结束会话 → 记忆升级
        self.memory.end_session(state.session_id, self.user_id)

        self._require_video_delivery(state)
        done_message = (
            "演示脚本已生成（Demo 模式未调用视频模型）"
            if self.demo_mode
            else "视频、脚本与投放素材已全部生成"
        )
        state.set_stage(AgentStage.DONE, done_message)

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

    def _require_video_enabled(self, state: AgentState):
        """Live 模式关闭视频时保留脚本并明确失败，禁止假完成。"""
        if self.demo_mode or self.enable_video:
            return
        message = (
            "脚本已生成，但视频生成功能未开启。请将 Railway Variables 中的 "
            "LIVE_ENABLE_VIDEO 设置为 true 并重新部署。"
        )
        state.set_video_stage("disabled", message)
        raise RuntimeError(message)

    def _require_video_delivery(self, state: AgentState):
        """Live 模式只有同时拿到站内 URL 和本地成片路径才能完成。"""
        if self.demo_mode:
            return
        if state.video_url and state.video_path:
            return
        message = (
            "脚本已生成，但没有生成可播放的视频成片；"
            "任务不会标记完成，请根据 Wan2.2 任务状态检查失败原因。"
        )
        state.set_video_stage("delivery_failed", message)
        raise RuntimeError(message)

    def _generate_bundle(self, state: AgentState) -> dict:
        """调用 LLM 生成完整的 Creative Bundle"""

        product = state.product_input

        # 构建 user message
        user_message = self._build_user_message(state)

        if self.demo_mode:
            # Demo 模式：返回模拟输出
            bundle = self._demo_generate(product)
        else:
            # Live 模式：调用 DashScope
            bundle = self._llm_generate(user_message)

        return self._normalize_10s_bundle(bundle, product)

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

        # 构建 10 秒双镜 Prompt（2 段 × 5s，共享视觉 DNA）
        sp_text = "，".join(selling_points[:3])
        taste_text = "，".join(taste_tags)
        scene_text = use_scene[0] if use_scene else "追剧"

        VISUAL_DNA = (
            "Vertical 9:16 smartphone video, 720p. "
            "Warm food lighting, natural color grading, appetizing food cinematography, "
            "handheld slight camera shake, cinematic depth of field. "
        )

        wan22_prompts = [
            (
                VISUAL_DNA
                + f"Use the uploaded product package as the exact first frame and preserve its logo, "
                f"colors, typography and package shape. Opening shot: the package stays clearly visible "
                f"beside a macro close-up of {product_name}. Camera slowly pushes in, warm amber light, "
                f"shallow depth of field, appetizing texture. Do not alter any packaging text. 5 seconds."
            ),
            (
                VISUAL_DNA
                + f"Use the uploaded product package as the exact first frame and preserve its logo, "
                f"colors, typography and package shape. Show the package in a cozy {scene_text} setting, "
                f"then a hand naturally picks up one piece of {product_name}. Keep the package readable "
                f"in frame and end on a clean product hero shot with space for a CTA overlay. 5 seconds."
            ),
        ]

        # 人群定向
        audience = suggest_audience(category, selling_points)

        return {
            "product_name": product_name,
            "script_type": script_type,
            "hook": hook,
            "multi_shot": True,
            "shots": [
                {
                    "time": "0-5s",
                    "label": "钩子开场",
                    "scene": f"{product_name}黄金酥脆特写，蒸汽升腾，质感拉满",
                    "copy": f"这个{product_name}你们一定要试试，{sp_text}，不是那种普通零食",
                    "wan22_prompt": wan22_prompts[0],
                    "effect": "微距推镜头+慢动作",
                },
                {
                    "time": "5-10s",
                    "label": "卖点转化",
                    "scene": f"{scene_text}场景中展示真实包装，手拿产品试吃，最后回到商品主视觉",
                    "copy": f"{taste_text}口感，{sp_text}。{unit_price}元到手，左下角链接去试试",
                    "wan22_prompt": wan22_prompts[1],
                    "effect": "手持POV+商品定格+CTA",
                },
            ],
            "storyboard": [  # 兼容旧版前端
                {
                    "time": "0-5s",
                    "scene": f"{product_name}特写",
                    "copy": hook,
                    "effect": "微距+慢动作",
                },
                {
                    "time": "5-10s",
                    "scene": f"试吃{product_name}",
                    "copy": f"{sp_text}，{taste_text}口感，{unit_price}元到手",
                    "effect": "手持POV+下单引导",
                },
            ],
            "wan22_prompt": wan22_prompts[0],  # 兼容旧版单镜调用
            "ad_titles": [
                f"{product_name}，{unit_price}元到手！追剧必备",
                f"还在吃贵的？{product_name}只要{unit_price}，{selling_points[0] if selling_points else '超好吃'}",
                f"{'，'.join(selling_points[:2])}的{category}，{unit_price}元你还要啥自行车",
            ],
            "suggested_audience": audience,
            "creative_rationale": f"10秒双镜{script_type}型，前5秒用真实包装建立识别，后5秒通过{'价格优势' if script_type == '对比测评' else '场景共鸣'}推动转化",
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

    def _normalize_10s_bundle(self, bundle: dict, product: dict) -> dict:
        """把 LLM 或 Demo 输出统一成两个 5 秒镜头。"""
        if not isinstance(bundle, dict):
            bundle = {}

        product_name = product.get("product_name", "零食")
        features = product.get("features", {})
        selling_points = features.get("selling_points") or ["口感好", "性价比高"]
        use_scene = features.get("use_scene") or ["追剧"]
        price = product.get("price", {}).get("unit_price", 9.9)
        visual_dna = (
            "Vertical 9:16 smartphone food advertisement, 720p, warm natural lighting, "
            "appetizing detail, subtle handheld movement, cinematic depth of field. "
            "Use the uploaded product package as the exact first frame. Preserve the logo, "
            "colors, typography and package shape; do not alter packaging text. "
        )

        existing_shots = bundle.get("shots") if isinstance(bundle.get("shots"), list) else []
        storyboard = bundle.get("storyboard") if isinstance(bundle.get("storyboard"), list) else []
        source = existing_shots or storyboard
        default_scenes = [
            f"真实包装与{product_name}质感特写",
            f"{use_scene[0]}场景展示，最后回到真实包装和下单引导",
        ]
        default_copies = [
            bundle.get("hook") or f"这个{product_name}，第一口就很上头",
            f"{'、'.join(selling_points[:2])}，{price}元到手，左下角链接去试试",
        ]

        shots = []
        for index in range(2):
            item = source[index] if index < len(source) and isinstance(source[index], dict) else {}
            scene = item.get("scene") or default_scenes[index]
            if index == 0:
                motion = (
                    f"Opening shot: {scene}. Keep the package clearly readable while the camera "
                    "slowly pushes in and reveals appetizing product texture. 5 seconds."
                )
                label = "钩子开场"
            else:
                motion = (
                    f"Conversion shot: {scene}. Place the package in a cozy {use_scene[0]} setting, "
                    "show a natural hand interaction, and end on a clean product hero frame with "
                    "space for a CTA overlay. 5 seconds."
                )
                label = "卖点转化"
            raw_prompt = item.get("wan22_prompt") or motion
            if "uploaded product package" not in raw_prompt.lower():
                raw_prompt = visual_dna + raw_prompt
            shots.append({
                "time": "0-5s" if index == 0 else "5-10s",
                "label": item.get("label") or label,
                "scene": scene,
                "copy": item.get("copy") or default_copies[index],
                "wan22_prompt": raw_prompt,
                "effect": item.get("effect") or ("微距推镜" if index == 0 else "场景展示+商品定格"),
            })

        bundle["product_name"] = bundle.get("product_name") or product_name
        bundle["multi_shot"] = True
        bundle["target_duration"] = 10
        bundle["shots"] = shots
        bundle["storyboard"] = [
            {key: shot[key] for key in ("time", "scene", "copy", "effect")}
            for shot in shots
        ]
        bundle["wan22_prompt"] = shots[0]["wan22_prompt"]
        return bundle

    def _product_image_input(self, product_input: dict) -> str:
        """把上传的商品图转成 DashScope 可读取的公网 URL 或 Base64 data URL。"""
        assets = product_input.get("assets") or {}
        image_ref = assets.get("product_main_image")
        if not image_ref:
            images = assets.get("product_images") or []
            image_ref = images[0] if images else ""
        if not image_ref:
            raise RuntimeError("请先上传商品主图；真实视频生成必须使用商品图片")

        if image_ref.startswith(("http://", "https://", "data:image/")):
            return image_ref

        filename = os.path.basename(image_ref.split("?", 1)[0])
        image_path = os.path.abspath(os.path.join(self.upload_dir, filename))
        if os.path.commonpath([self.upload_dir, image_path]) != self.upload_dir:
            raise RuntimeError("商品图片路径无效")
        if not os.path.isfile(image_path):
            raise RuntimeError("找不到已上传的商品主图，请重新上传后再生成")

        size = os.path.getsize(image_path)
        if size > 10 * 1024 * 1024:
            raise RuntimeError("Wan2.2 商品主图不能超过 10MB")
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        if mime not in {"image/jpeg", "image/png", "image/webp", "image/bmp"}:
            raise RuntimeError("商品主图仅支持 JPG、PNG、WebP 或 BMP")
        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _generate_10s_video(self, bundle: dict, state: AgentState) -> tuple[str, str]:
        """两次真实 I2V → 精确拼接为 10 秒 → 保存为站内永久地址。"""
        image_input = self._product_image_input(state.product_input)
        shots = (bundle.get("shots") or [])[:2]
        if len(shots) != 2:
            raise RuntimeError("10 秒广告需要两个 5 秒镜头")

        task_ids = []
        for index, shot in enumerate(shots):
            prompt = shot.get("wan22_prompt", "").strip()
            if not prompt:
                raise RuntimeError(f"第 {index + 1} 镜缺少视频 Prompt")
            shot_number = index + 1
            label = shot.get("label", f"镜头{shot_number}")
            state.set_video_stage(
                f"submitting_{shot_number}",
                f"正在提交第 {shot_number}/2 段 Wan2.2 图生视频",
            )
            print(f"[Agent] 正在提交第 {shot_number}/2 段 Wan2.2...")
            try:
                result = self.wan22.i2v(
                    image_url=image_input,
                    prompt=prompt,
                    duration=5,
                    resolution="720P",
                )
            except Exception as error:
                safe_error = safe_error_message(error)
                state.set_video_stage(
                    f"submit_failed_{shot_number}",
                    f"第 {shot_number}/2 段 Wan2.2 提交失败",
                )
                raise RuntimeError(
                    f"WAN_SUBMIT_SHOT_{shot_number}_FAILED: {safe_error}"
                ) from error
            task_ids.append((index, label, result.task_id))
            state.record_video_task(shot_number, label, result.task_id)
            state.set_video_stage(
                f"submitted_{shot_number}",
                f"第 {shot_number}/2 段已提交，任务编号已保存",
            )
            print(
                f"[Agent] 第 {shot_number}/2 段 Wan2.2 已提交并持久化, "
                f"task_id={result.task_id}"
            )
            state.add_step(
                thought=f"提交第 {shot_number}/2 镜真实图生视频",
                action="wan22_i2v",
                action_input={
                    "shot": shot_number,
                    "duration": 5,
                    "uses_product_image": True,
                    "prompt": prompt[:80],
                },
                observation=f"task_id={result.task_id}",
            )

        state.set_video_stage(
            "waiting",
            "两段 Wan2.2 均已提交，正在等待云端渲染",
        )
        video_urls = []
        failures = []
        for index, label, task_id in task_ids:
            shot_number = index + 1
            state.set_video_stage(
                f"rendering_{shot_number}",
                f"正在等待第 {shot_number}/2 段 Wan2.2 渲染",
            )
            final = self.wan22.wait(
                task_id,
                max_wait=600,
                on_update=lambda update, task_id=task_id: state.update_video_task(
                    task_id,
                    update.status.value,
                    safe_error_message(update.error_message)
                    if update.error_message
                    else None,
                ),
            )
            if final.status == TaskStatus.SUCCEEDED and final.video_url:
                video_urls.append((index, label, final.video_url))
            else:
                failures.append(f"第{index + 1}镜：{final.error_message or final.status.value}")
        if failures:
            raise RuntimeError("视频生成失败；" + "；".join(failures))

        return self._compose_video_urls(bundle, state, video_urls)

    def recover_video_from_existing_tasks(
        self,
        state: AgentState,
    ) -> tuple[str, str]:
        """仅查询已保存的 Wan2.2 task_id 并重新合成，绝不创建新任务。"""
        if self.demo_mode:
            raise RuntimeError("Demo 模式没有可恢复的 Wan2.2 视频任务")
        if not state.creative_bundle:
            raise RuntimeError("该任务没有已保存的双镜脚本，无法恢复合成")

        tasks = sorted(
            (
                task
                for task in state.video_tasks
                if task.get("task_id") and task.get("shot") in (1, 2)
            ),
            key=lambda task: task["shot"],
        )
        if len(tasks) != 2 or {task["shot"] for task in tasks} != {1, 2}:
            raise RuntimeError("恢复合成需要两个已保存的 Wan2.2 task_id")

        state.error = None
        state.video_url = None
        state.video_path = None
        state.set_stage(
            AgentStage.RENDERING,
            "正在复用已保存的 Wan2.2 任务，不会重新提交视频生成",
        )

        video_urls = []
        failures = []
        for task in tasks:
            shot_number = task["shot"]
            task_id = task["task_id"]
            label = task.get("label") or f"镜头{shot_number}"
            state.set_video_stage(
                f"recovering_{shot_number}",
                f"正在读取第 {shot_number}/2 段已有 Wan2.2 结果",
            )
            final = self.wan22.wait(
                task_id,
                max_wait=600,
                on_update=lambda update, task_id=task_id: state.update_video_task(
                    task_id,
                    update.status.value,
                    safe_error_message(update.error_message)
                    if update.error_message
                    else None,
                ),
            )
            if final.status == TaskStatus.SUCCEEDED and final.video_url:
                video_urls.append((shot_number - 1, label, final.video_url))
            else:
                failures.append(
                    f"第{shot_number}镜："
                    f"{final.error_message or final.status.value}"
                )

        if failures:
            raise RuntimeError("已有 Wan2.2 任务无法恢复；" + "；".join(failures))

        video_url, video_path = self._compose_video_urls(
            state.creative_bundle,
            state,
            video_urls,
        )
        state.video_url = video_url
        state.video_path = video_path
        state.error = None
        state.checkpoint()
        self._require_video_delivery(state)
        state.set_stage(
            AgentStage.DONE,
            "已复用原 Wan2.2 任务完成视频合成，未重新提交生成",
        )
        return video_url, video_path

    @staticmethod
    def _run_ffmpeg(command: list[str], label: str):
        """运行 FFmpeg；失败时把完整 stdout/stderr 写入 Railway 日志。"""
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.CalledProcessError as error:
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            print(
                f"[FFmpeg] {label}失败，exit_code={error.returncode}\n"
                f"[FFmpeg] stdout:\n{stdout}\n"
                f"[FFmpeg] stderr:\n{stderr}"
            )
            detail = next(
                (line.strip() for line in reversed(stderr.splitlines()) if line.strip()),
                f"exit_code={error.returncode}",
            )
            raise RuntimeError(f"{label}失败：{detail}") from error

    def _compose_video_urls(
        self,
        bundle: dict,
        state: AgentState,
        video_urls: list[tuple[int, str, str]],
    ) -> tuple[str, str]:
        """下载两个已有视频地址并用固定英文 FFmpeg 参数合成为成片。"""
        shots = (bundle.get("shots") or [])[:2]
        if len(shots) != 2:
            raise RuntimeError("10 秒广告需要两个 5 秒镜头")

        tmpdir = tempfile.mkdtemp(prefix="snack_video_")
        try:
            state.set_video_stage(
                "downloading",
                "两段视频已生成，正在下载并准备拼接",
            )
            video_files = []
            for index, label, url in sorted(video_urls):
                video_path = os.path.join(tmpdir, f"shot_{index + 1}.mp4")
                response = httpx.get(url, timeout=180, follow_redirects=True)
                response.raise_for_status()
                with open(video_path, "wb") as video_file:
                    video_file.write(response.content)
                video_files.append(video_path)

            if len(video_files) != 2:
                raise RuntimeError("未能下载完整的两个视频镜头")

            merged_path = os.path.join(tmpdir, "merged_10s.mp4")
            state.set_video_stage("merging", "正在将两段视频拼接为 10 秒成片")
            concat_filter = (
                f"[0:v]fps=25,scale=720:1280:"
                f"force_original_aspect_ratio={self.FFMPEG_ASPECT_RATIO_MODE},"
                "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[v0];"
                f"[1:v]fps=25,scale=720:1280:"
                f"force_original_aspect_ratio={self.FFMPEG_ASPECT_RATIO_MODE},"
                "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[v1];"
                "[v0][v1]concat=n=2:v=1:a=0,trim=duration=10,setpts=PTS-STARTPTS[vout]"
            )
            self._run_ffmpeg(
                [
                    "ffmpeg", "-y", "-i", video_files[0], "-i", video_files[1],
                    "-filter_complex", concat_filter, "-map", "[vout]",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "21",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", merged_path,
                ],
                "双镜视频拼接",
            )

            filename = f"{state.session_id}_10s.mp4"
            final_path = os.path.join(self.output_dir, filename)
            script_text = " ".join(shot.get("copy", "") for shot in shots if shot.get("copy"))
            source_path = merged_path
            if script_text:
                state.set_video_stage("voiceover", "正在为 10 秒成片合成口播")
                voice_path = os.path.join(tmpdir, "voice.mp3")
                voiced_path = os.path.join(tmpdir, "voiced_10s.mp4")
                try:
                    subprocess.run(
                        [
                            "edge-tts", "--voice", "zh-CN-XiaoyiNeural",
                            "--text", script_text, "--write-media", voice_path,
                        ],
                        check=True,
                        capture_output=True,
                        timeout=120,
                    )
                    self._run_ffmpeg(
                        [
                            "ffmpeg", "-y", "-i", merged_path, "-i", voice_path,
                            "-filter_complex", "[1:a]apad=pad_dur=10[a]",
                            "-map", "0:v:0", "-map", "[a]", "-c:v", "copy",
                            "-c:a", "aac", "-t", "10", "-movflags", "+faststart", voiced_path,
                        ],
                        "口播音视频合成",
                    )
                    source_path = voiced_path
                    state.add_step(
                        thought="10秒口播已合成",
                        action="voiceover",
                        action_input={"script": script_text[:80]},
                        observation="duration=10",
                    )
                except Exception as error:
                    print(f"[Agent] 口播合成失败，保留无声成片: {error}")

            shutil.copy2(source_path, final_path)
            state.set_video_stage("completed", "10 秒成片已保存")
            state.add_step(
                thought="两个真实图生视频镜头已拼接并永久保存",
                action="video_concat",
                action_input={"shots": 2, "target_duration": 10},
                observation=f"output=/outputs/{filename}",
            )
            return f"/outputs/{filename}", final_path
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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
