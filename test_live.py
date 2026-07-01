# -*- coding: utf-8 -*-
"""
Live 模式端到端测试

用法:
    # 不生成视频（安全，不产生费用）
    set DASHSCOPE_API_KEY=sk-your-api-key
    python test_live.py

    # 生成视频（产生 Wan2.2 费用）
    set DASHSCOPE_API_KEY=sk-your-api-key
    set LIVE_ENABLE_VIDEO=true
    python test_live.py
"""

import json
import os
import sys
import io

# 强制 UTF-8 输出，解决 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 强制 Live 模式
os.environ["AGENT_MODE"] = "live"

from config import settings
from layer3_memory import create_memory_manager
from layer6_execution import CreativeAgent

# ═══════════════════════════════════════════
# 检查 API Key
# ═══════════════════════════════════════════

api_key = settings.DASHSCOPE_API_KEY
if not api_key:
    print("=" * 60)
    print("[ERROR] 未设置 DASHSCOPE_API_KEY 环境变量")
    print("=" * 60)
    print()
    print("请先设置环境变量:")
    print('  Windows: set DASHSCOPE_API_KEY=sk-xxxxxxxx')
    print('  Mac/Linux: export DASHSCOPE_API_KEY=sk-xxxxxxxx')
    print()
    print("获取 API Key: https://dashscope.console.aliyun.com/apiKey")
    sys.exit(1)

print("=" * 60)
print("Live 模式端到端测试")
print(f"   API Key: {api_key[:12]}...{api_key[-4:]}")
print(f"   视频生成: {'开启' if settings.LIVE_ENABLE_VIDEO else '关闭（安全模式）'}")
print("=" * 60)

# ═══════════════════════════════════════════
# 初始化各层
# ═══════════════════════════════════════════

print("\n[1/4] 初始化记忆层...")
memory_manager = create_memory_manager(
    sqlite_path="./data/live_test.db",
    chroma_path="./data/live_test_chroma",
)

print("[2/4] 创建 Agent（Live 模式）...")
agent = CreativeAgent(
    memory_manager=memory_manager,
    dashscope_api_key=api_key,
    user_id="test_user_live",
    demo_mode=False,
    enable_video=settings.LIVE_ENABLE_VIDEO,
)

# ═══════════════════════════════════════════
# 构建测试产品
# ═══════════════════════════════════════════

test_product = {
    "product_name": "三只松鼠每日坚果",
    "category_l1": "休闲零食",
    "category_l2": "坚果炒货",
    "price": {
        "unit_price": 29.9,
        "original_price": 89.0,
        "discount_rate": 0.34,
    },
    "features": {
        "selling_points": ["每日鲜烤", "6种坚果混合", "独立小包装", "非油炸"],
        "taste_tags": ["原香", "酥脆", "微甜"],
        "use_scene": ["办公室", "追剧", "早餐"],
        "stock_status": "充足",
    },
}

print(f"\n[3/4] 测试产品: {test_product['product_name']}")
print(f"   类目: {test_product['category_l1']} > {test_product['category_l2']}")
print(f"   价格: {test_product['price']['unit_price']}元 (原价 {test_product['price']['original_price']}元)")

# ═══════════════════════════════════════════
# 运行 Agent
# ═══════════════════════════════════════════

print("\n[4/4] 执行 Agent ReAct 循环...\n")
print("-" * 60)

state = agent.run(test_product, session_id="live_test_001")

# ═══════════════════════════════════════════
# 输出结果
# ═══════════════════════════════════════════

print("-" * 60)
print(f"\n{'=' * 60}")
print("测试结果")
print("=" * 60)

print(f"\n状态: {state.stage.value}")
if state.error:
    print(f"[ERROR] 错误: {state.error}")
    sys.exit(1)

bundle = state.creative_bundle
if not bundle:
    print("[ERROR] 未生成 Creative Bundle")
    sys.exit(1)

print(f"\n## 素材方案")
print(f"  商品: {bundle.get('product_name', '-')}")
print(f"  创意类型: {bundle.get('script_type', '-')}")
print(f"  钩子: {bundle.get('hook', '-')}")
print(f"  创意理由: {bundle.get('creative_rationale', '-')}")

print(f"\n## 分镜脚本")
for s in bundle.get("storyboard", []):
    print(f"  [{s.get('time', '-')}] {s.get('scene', '-')}")
    print(f"   -> {s.get('copy', '-')}")

print(f"\n## Wan2.2 Prompt")
print(f"  {bundle.get('wan22_prompt', '-')[:200]}...")

print(f"\n## 投放标题")
for i, title in enumerate(bundle.get("ad_titles", [])):
    print(f"  {i+1}. {title}")

print(f"\n## 人群定向")
audience = bundle.get("suggested_audience", {})
print(f"  性别: {audience.get('gender', '-')}")
print(f"  年龄: {audience.get('age', '-')}")
print(f"  兴趣: {', '.join(audience.get('interests', []))}")
print(f"  城市: {audience.get('city_level', '-')}")

print(f"\n## ReAct 步骤")
for i, step in enumerate(state.steps):
    print(f"  Step {i+1}: {step.action}")
    print(f"  思考: {step.thought[:100]}...")

print(f"\nLive 模式测试完成！")
