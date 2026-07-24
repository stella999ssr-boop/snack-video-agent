"""
第1层 · 用户输入 — Pydantic 数据模型
14个字段，5个分类
"""

from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from typing import Optional


class PriceInfo(BaseModel):
    """价格信息"""
    unit_price: float = Field(..., description="单价（元），如 9.9")
    original_price: Optional[float] = Field(None, description="原价（元），如 39.9")
    discount_rate: Optional[float] = Field(None, description="折扣率，如 0.25（即2.5折）")


class ProductFeatures(BaseModel):
    """产品特征"""
    selling_points: list[str] = Field(..., description="卖点标签，如 ['非油炸', '酥脆', '性价比高']")
    taste_tags: list[str] = Field(..., description="口味特征，如 ['麻辣', '咸香']")
    use_scene: Optional[list[str]] = Field(None, description="适用场景，如 ['追剧', '办公室', '聚会']")
    season_tag: Optional[str] = Field(None, description="季节标签，如 '四季通用'/'夏季'/'冬季'")
    stock_status: Optional[str] = Field(None, description="库存状态，如 '充足'/'紧张'/'预售'")


class ProductAssets(BaseModel):
    """素材资源"""
    product_main_image: Optional[str] = Field(None, description="商业主图 URL")
    product_images: Optional[list[str]] = Field(None, description="商品照片 URL 列表")
    product_video: Optional[str] = Field(None, description="商品视频 URL（原始素材）")


class CreativeInput(BaseModel):
    """素材生成完整输入"""

    # 基础信息
    product_name: str = Field(..., description="商品名称，如 'XX牌香辣薯条'")
    category_l1: str = Field(..., description="一级类目，如 '休闲零食'")
    category_l2: str = Field(..., description="二级类目，如 '膨化食品'")

    # 价格信息
    price: PriceInfo

    # 产品特征
    features: ProductFeatures

    # 商业关联
    shop_product_id: str = Field(..., description="抖音小店商品 ID")
    shop_product_url: Optional[str] = Field(None, description="抖音小店商品链接")

    # 素材资源
    assets: Optional[ProductAssets] = None

    # 用户偏好（可选覆写）
    preferred_style: Optional[str] = Field(None, description="用户指定风格，如 '知识科普型'")
    target_duration: int = Field(10, ge=10, le=10, description="目标视频时长（秒），当前固定为10")


class CreativeInputResponse(BaseModel):
    """素材生成输入 — 确认响应"""
    request_id: str
    status: str
    message: str
    product_name: str


class ManualVideoRecoveryInput(BaseModel):
    """手动提供两个既有 Wan2.2 任务编号，仅用于查询与合成。"""

    shot_1_task_id: UUID = Field(..., description="第 1 段 Wan2.2 task_id")
    shot_2_task_id: UUID = Field(..., description="第 2 段 Wan2.2 task_id")

    @model_validator(mode="after")
    def require_distinct_task_ids(self):
        if self.shot_1_task_id == self.shot_2_task_id:
            raise ValueError("两段视频的 task_id 不能相同")
        return self
