"""衣物 API 的请求 / 响应模型。

三条硬约束：

1. `extra="forbid"` —— 请求体里出现 `user_id`、`id`、`public_id`、`created_at`
   等任何未声明字段都会被 **422 拒绝**。归属只可能来自服务端身份上下文，
   客户端连"试图指定"的入口都没有。
2. `str_strip_whitespace=True` + `min_length=1` —— `"   "` 这类全空白名称被拒。
3. `category` 直接用 `ItemCategory` 枚举 —— 类别集合只有一个事实来源
   （与数据库 CHECK 约束同源），不在这里另抄一份列表。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import ItemCategory

# 与数据库列长度保持一致（items.name VARCHAR(120) / color VARCHAR(32) / image_ref VARCHAR(512)）
ItemName = Annotated[str, Field(min_length=1, max_length=120)]
ItemColor = Annotated[str, Field(max_length=32)]
ImageRef = Annotated[str, Field(max_length=512)]


def _blank_to_none(value: str | None) -> str | None:
    """可选文本字段：空串视为"没填"，统一存 NULL。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ItemCreate(BaseModel):
    """创建衣物。**没有** user_id 字段，也不接受任何归属类字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ItemName = Field(description="衣物名称，如「白色牛津纺衬衫」")
    category: ItemCategory = Field(description="衣物类别，取值见 ItemCategory")
    color: ItemColor | None = Field(default=None, description="颜色，可空")
    image_ref: str | None = Field(
        default=None,
        max_length=512,
        description="图片引用键（本阶段只保存已有引用，不提供上传接口）",
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("衣物名称不能为空或全空白")
        return value

    @field_validator("color", "image_ref")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ItemUpdate(BaseModel):
    """局部更新。所有字段可省略；显式传 `null` 表示清空（name/category 除外）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ItemName | None = Field(default=None, description="新名称")
    category: ItemCategory | None = Field(default=None, description="新类别")
    color: ItemColor | None = Field(default=None, description="新颜色；传 null 表示清空")
    image_ref: str | None = Field(default=None, description="新的图片引用；传 null 表示清空")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("衣物名称不能为空或全空白")
        return value

    @field_validator("color", "image_ref")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @model_validator(mode="after")
    def _reject_explicit_null_for_required(self) -> ItemUpdate:
        # 数据库里 name / category 是 NOT NULL，显式传 null 必须拒绝，
        # 而不是悄悄当作"没改"（那会让调用方以为改动生效了）
        for field in ("name", "category"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} 不允许为 null；如需保持原值请直接省略该字段")
        return self


class ItemRead(BaseModel):
    """衣物对外表示。只暴露服务端生成的字段，且不含 user_id（调用方无需也不应知道）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: ItemCategory
    color: str | None
    image_ref: str | None
    created_at: datetime
    updated_at: datetime


class ItemListResponse(BaseModel):
    items: list[ItemRead]
    total: int = Field(description="当前用户衣物总数（用于分页）")
    limit: int
    offset: int
