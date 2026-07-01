"""
定向人群标签字典

约束 LLM 的人群建议输出，确保每次生成的标签在千川后台可用的标签范围内。
LLM 不得编造不存在的标签。
"""

from typing import Optional


# ═══════════════════════════════════════════════════
# 类目树（一级 → 二级 联动）
# ═══════════════════════════════════════════════════

CATEGORY_TREE: dict[str, list[str]] = {
    "休闲零食": [
        "膨化食品", "坚果炒货", "肉干肉脯", "糖果巧克力",
        "饼干糕点", "蜜饯果干", "豆干素食", "海味零食",
    ],
    "冲调饮品": [
        "饮料冲调", "咖啡麦片", "代餐奶昔", "茶饮花茶",
    ],
    "方便速食": [
        "方便面/粉", "自热食品", "速食汤粥", "预制快手菜",
    ],
    "烘焙糕点": [
        "面包吐司", "蛋糕西点", "中式糕点", "蛋黄酥/月饼",
    ],
}


# ═══════════════════════════════════════════════════
# 标签体系
# ═══════════════════════════════════════════════════

TAG_DICTIONARY: dict[str, list[str]] = {
    # 性别
    "gender": ["不限", "男性", "女性"],

    # 年龄区间
    "age": ["不限", "18-23", "24-30", "31-35", "36-40", "41-50", "51+"],

    # 兴趣标签（千川后台实际支持的类目）
    "interests": [
        "零食", "美食", "追剧", "学生党", "办公室",
        "宝妈", "健康饮食", "减脂", "夜宵",
        "性价比", "囤货", "开箱", "小吃", "特产",
        "进口零食", "怀旧零食", "熬夜", "聚会",
        "送礼", "自用", "学生宿舍", "上班族",
        "膨化食品", "坚果炒货", "肉干肉脯", "糖果巧克力",
        "饼干糕点", "方便速食", "饮料冲调",
    ],

    # 城市等级
    "city_level": ["不限", "一线", "新一线", "二线", "三线", "四线", "五线"],
}


# ═══════════════════════════════════════════════════
# 品类 → 人群映射（基于经验，Agent 生成时参考）
# ═══════════════════════════════════════════════════

CATEGORY_AUDIENCE_MAP: dict[str, dict] = {
    "膨化食品": {
        "primary": {"age": "18-23", "interests": ["零食", "学生党", "追剧"]},
        "secondary": {"age": "24-30", "interests": ["办公室", "夜宵", "囤货"]},
    },
    "坚果炒货": {
        "primary": {"age": "24-35", "interests": ["健康饮食", "办公室", "零食"]},
        "secondary": {"age": "不限", "interests": ["送礼", "特产", "怀旧零食"]},
    },
    "肉干肉脯": {
        "primary": {"age": "18-30", "interests": ["追剧", "夜宵", "学生党"]},
        "secondary": {"age": "24-35", "interests": ["办公室", "聚会", "小吃"]},
    },
    "糖果巧克力": {
        "primary": {"age": "18-30", "interests": ["送礼", "学生党", "零食"]},
        "secondary": {"age": "18-23", "interests": ["情人节", "礼物", "进口零食"]},
    },
    "饼干糕点": {
        "primary": {"age": "24-35", "interests": ["办公室", "宝妈", "性价比"]},
        "secondary": {"age": "不限", "interests": ["零食", "囤货", "送礼"]},
    },
    "方便速食": {
        "primary": {"age": "18-30", "interests": ["学生宿舍", "熬夜", "夜宵"]},
        "secondary": {"age": "24-35", "interests": ["办公室", "上班族", "性价比"]},
    },
    "饮料冲调": {
        "primary": {"age": "18-30", "interests": ["学生党", "追剧", "零食"]},
        "secondary": {"age": "24-35", "interests": ["办公室", "宝妈", "健康饮食"]},
    },
}


# ═══════════════════════════════════════════════════
# 校验 & 建议
# ═══════════════════════════════════════════════════

def validate_audience(audience: dict) -> tuple[bool, list[str]]:
    """
    校验人群定向是否在标签字典内。
    返回: (是否全部有效, 无效标签列表)
    """
    invalid = []

    if audience.get("gender") and audience["gender"] not in TAG_DICTIONARY["gender"]:
        invalid.append(f"gender: {audience['gender']}")

    if audience.get("age") and audience["age"] not in TAG_DICTIONARY["age"]:
        invalid.append(f"age: {audience['age']}")

    for interest in audience.get("interests", []):
        if interest not in TAG_DICTIONARY["interests"]:
            invalid.append(f"interest: {interest}")

    if audience.get("city_level") and audience["city_level"] not in TAG_DICTIONARY["city_level"]:
        invalid.append(f"city_level: {audience['city_level']}")

    return len(invalid) == 0, invalid


def suggest_audience(category: str, selling_points: Optional[list[str]] = None) -> dict:
    """
    根据品类和卖点自动推荐人群标签。
    Agent 无 LLM 参与时可用此做降级输出。
    """
    mapping = CATEGORY_AUDIENCE_MAP.get(category, {})
    primary = mapping.get("primary", {"age": "不限", "interests": ["零食"]})
    secondary = mapping.get("secondary", {"age": "不限", "interests": ["美食"]})

    # 合并主次人群的兴趣标签（去重）
    all_interests = list(dict.fromkeys(
        primary.get("interests", []) + secondary.get("interests", [])
    ))[:5]

    # 根据卖点调整
    if selling_points:
        if any("健康" in s or "非油炸" in s or "减脂" in s for s in selling_points):
            if "健康饮食" not in all_interests:
                all_interests.insert(0, "健康饮食")
        if any("便宜" in s or "性价比" in s or "9.9" in s for s in selling_points):
            if "性价比" not in all_interests:
                all_interests.insert(0, "性价比")
        if any("囤货" in s or "大包装" in s for s in selling_points):
            if "囤货" not in all_interests:
                all_interests.append("囤货")

    return {
        "gender": "不限",
        "age": primary.get("age", "不限"),
        "interests": all_interests[:5],
        "city_level": "不限",
    }


def get_tags_for_prompt() -> str:
    """生成注入 LLM prompt 的标签体系说明"""
    return f"""
## 人群定向标签（仅可使用以下值）

- 性别: {', '.join(TAG_DICTIONARY['gender'])}
- 年龄: {', '.join(TAG_DICTIONARY['age'])}
- 城市等级: {', '.join(TAG_DICTIONARY['city_level'])}
- 兴趣标签（最多5个）: {', '.join(TAG_DICTIONARY['interests'])}
"""
