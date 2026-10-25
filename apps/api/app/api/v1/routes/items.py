"""衣物 CRUD 路由。

安全要点：
- 归属永远来自 `get_user_context`，路由体里没有任何 user_id 入参；
- 查询他人衣物与查询不存在的衣物返回**完全相同**的 404，不泄露资源存在性；
- 不把异常、SQL 或连接串写进响应（由 `app/core/errors.py` 统一兜底）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import ItemRepositoryDep
from app.api.v1.schemas.item import ItemCreate, ItemListResponse, ItemRead, ItemUpdate
from app.core.errors import NotFoundError

router = APIRouter(prefix="/items", tags=["items"])

# 统一的"衣物不存在"错误：越权访问与真的不存在走同一个错误对象。
# 不区分二者是刻意的 —— 区分就等于告诉攻击者"这个 id 存在，只是不属于你"。
_ITEM_NOT_FOUND_CODE = "item_not_found"
_ITEM_NOT_FOUND_MESSAGE = "衣物不存在"

ItemIdPath = Annotated[int, Path(ge=1, description="衣物 ID")]


def _not_found() -> NotFoundError:
    return NotFoundError(_ITEM_NOT_FOUND_MESSAGE, code=_ITEM_NOT_FOUND_CODE)


@router.post(
    "",
    response_model=ItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="新增衣物",
    description=(
        "为**当前用户**创建衣物。归属由服务端身份上下文决定，"
        "请求体中出现 user_id / id 等未声明字段会被 422 拒绝。"
    ),
)
def create_item(payload: ItemCreate, repo: ItemRepositoryDep) -> ItemRead:
    item = repo.create_item(
        name=payload.name,
        category=payload.category.value,
        color=payload.color,
        image_ref=payload.image_ref,
    )
    return ItemRead.model_validate(item)


@router.get(
    "",
    response_model=ItemListResponse,
    summary="列出我的衣物",
    description="只返回当前用户的衣物，按创建时间倒序。",
)
def list_items(
    repo: ItemRepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 50,
    offset: Annotated[int, Query(ge=0, description="跳过条数")] = 0,
) -> ItemListResponse:
    items = repo.list_items(limit=limit, offset=offset)
    return ItemListResponse(
        items=[ItemRead.model_validate(item) for item in items],
        total=repo.count_items(),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{item_id}",
    response_model=ItemRead,
    summary="查看单件衣物",
    responses={404: {"description": "衣物不存在或不属于当前用户"}},
)
def get_item(item_id: ItemIdPath, repo: ItemRepositoryDep) -> ItemRead:
    item = repo.get_item(item_id)
    if item is None:
        raise _not_found()
    return ItemRead.model_validate(item)


@router.patch(
    "/{item_id}",
    response_model=ItemRead,
    summary="修改衣物",
    description=(
        "局部更新，只改传入的字段。"
        "`color` / `image_ref` 传 `null` 表示清空；`name` / `category` 不允许显式 null。"
    ),
    responses={404: {"description": "衣物不存在或不属于当前用户"}},
)
def update_item(payload: ItemUpdate, item_id: ItemIdPath, repo: ItemRepositoryDep) -> ItemRead:
    data = payload.model_dump(exclude_unset=True)
    category = data.get("category")
    if category is not None:
        data["category"] = category.value

    item = repo.update_item(item_id, **data)
    if item is None:
        raise _not_found()
    return ItemRead.model_validate(item)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除衣物",
    description="删除成功返回 204 且无响应体；衣物不存在或不属于当前用户返回 404。",
    responses={404: {"description": "衣物不存在或不属于当前用户"}},
)
def delete_item(item_id: ItemIdPath, repo: ItemRepositoryDep) -> Response:
    if not repo.delete_item(item_id):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
