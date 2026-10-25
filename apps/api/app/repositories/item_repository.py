"""衣物仓储层（ItemRepository）。

设计原则：**隔离由构造决定，不由每个方法自觉决定。**

`ItemRepository` 构造时必须传入 `UserContext`，并且：
- 不提供任何接收 `user_id` 参数的公开方法；
- 不暴露 `session` 供调用方自行拼 SQL；
- 所有 SELECT / UPDATE / DELETE 的 WHERE 都同时包含 `user_id = ctx.user_id`。

于是"忘了加过滤条件"这种事故在类型层面就很难发生 —— 因为根本没有可以传
别人 user_id 的入参。

关于"不要先查出别人的记录再判断"：本实现里越权与不存在在 SQL 层就合并了，
UPDATE/DELETE 的 WHERE 直接带 user_id，命中 0 行即视为不存在，
不存在"先取出来再决定是否允许"的时间窗，也就没有据此泄露资源存在性的可能。

事务语义（实测得出，勿随手改）：
- 写方法内部 `commit()`，把一次操作作为一个工作单元提交；
- 该 Session 若由调用方加入外层事务，`commit()` 只释放 SAVEPOINT，外层事务仍在；
- 但 `rollback()` 会**连带撤掉外层事务**，因此只在真正的数据库异常时才回滚 ——
  "更新命中 0 行"这种正常分支不调用 rollback。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.user_context import UserContext
from app.models.item import Item

logger = logging.getLogger(__name__)

# 区分「调用方没传这个字段」与「调用方明确传了 None（要清空）」
_UNSET: Any = object()


class ItemRepository:
    """以 `UserContext` 为数据访问边界的衣物仓储。"""

    __slots__ = ("_ctx", "_session")

    def __init__(self, session: Session, ctx: UserContext) -> None:
        if not isinstance(ctx, UserContext):
            # 传 None 或随意传个 user_id 都会被挡在这里，避免"以为隔离了其实没隔离"
            raise TypeError("ItemRepository 必须接收 UserContext 实例")
        self._ctx = ctx
        self._session = session

    # -- 只读属性：便于日志与测试断言，但不能借此改写身份（UserContext 本身不可变）--
    @property
    def ctx(self) -> UserContext:
        return self._ctx

    @property
    def _user_id(self) -> int:
        return self._ctx.user_id

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_items(self, *, limit: int = 50, offset: int = 0) -> list[Item]:
        """列出当前用户的衣物，最近创建的在前。

        排序 `created_at DESC, id DESC`：`created_at` 可能同秒，
        补 `id DESC` 保证分页顺序稳定（否则翻页会重复/漏项）。
        """
        stmt = (
            select(Item)
            .where(Item.user_id == self._user_id)
            .order_by(Item.created_at.desc(), Item.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.execute(stmt).scalars().all())

    def count_items(self) -> int:
        """当前用户衣物总数（用于分页）。"""
        stmt = select(func.count()).select_from(Item).where(Item.user_id == self._user_id)
        return int(self._session.execute(stmt).scalar_one())

    def get_item(self, item_id: int) -> Item | None:
        """按 id 取当前用户的衣物；他人的或不存在的都返回 None（调用方统一 404）。"""
        stmt = select(Item).where(Item.user_id == self._user_id, Item.id == item_id)
        return self._session.execute(stmt).scalar_one_or_none()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def create_item(
        self,
        *,
        name: str,
        category: str,
        color: str | None = None,
        image_ref: str | None = None,
    ) -> Item:
        """创建衣物。归属固定取 `ctx.user_id`，**没有** user_id 入参。"""
        item = Item(
            user_id=self._user_id,
            name=name,
            category=category,
            color=color,
            image_ref=image_ref,
        )
        try:
            self._session.add(item)
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return item

    def update_item(
        self,
        item_id: int,
        *,
        name: Any = _UNSET,
        category: Any = _UNSET,
        color: Any = _UNSET,
        image_ref: Any = _UNSET,
    ) -> Item | None:
        """更新当前用户指定衣物。不存在或不属于当前用户都返回 None。

        用 `_UNSET` 而非 `None` 表示"未提供"，否则无法区分
        「不修改颜色」与「把颜色清空」。
        """
        values: dict[str, Any] = {}
        if name is not _UNSET:
            values["name"] = name
        if category is not _UNSET:
            values["category"] = category
        if color is not _UNSET:
            values["color"] = color
        if image_ref is not _UNSET:
            values["image_ref"] = image_ref

        if not values:
            # 空 patch：不写库，直接回读当前状态
            return self.get_item(item_id)

        stmt = (
            update(Item)
            .where(Item.user_id == self._user_id, Item.id == item_id)
            .values(**values)
        )
        try:
            result = self._session.execute(stmt)
            if result.rowcount == 0:
                # 没有匹配行。**刻意不调用 rollback()**：
                # 本方法没有写入任何东西，无需回滚；而 Session 若加入了调用方的
                # 外层事务，rollback() 会连带把外层事务一起撤掉（已实测），
                # 对调用方是意外破坏。仅在真正的数据库异常时才回滚。
                return None
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise

        # commit 后重新读取，确保返回的是数据库真实状态（含 updated_at）
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> bool:
        """删除当前用户指定衣物。返回是否真的删掉了一行。

        DELETE 的 WHERE 同样带 user_id，因此删除他人衣物时 rowcount 为 0，
        不会误删，也不会泄露"那条记录是否存在"。
        """
        stmt = delete(Item).where(Item.user_id == self._user_id, Item.id == item_id)
        try:
            result = self._session.execute(stmt)
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return result.rowcount > 0
