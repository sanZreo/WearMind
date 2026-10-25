"""用户上下文（UserContext）。

这是整个后端**唯一**的用户身份载体。设计约束：

1. `UserContext` 由后端在请求进入时解析，**绝不**由请求体、查询参数或普通请求头构造。
   客户端无法通过传 `user_id` 影响数据归属 —— 因为没有任何代码路径把客户端值
   写进 `UserContext`。
2. `frozen=True` + `slots=True`：不可变。仓储层拿到它之后无法被调用方改写，
   避免"中途换用户"这类隐蔽的越权路径。
3. `origin` 显式标注身份来源：
   - `development_identity`：本地开发用的固定身份（**不是认证**）
   - `authenticated`：将来接入正式认证后由会话/令牌解析得出（**尚未实现**）

> ⚠️ 当前版本只有 `development_identity` 一种来源，且仅在 `APP_ENV=development`
> 且显式开启 `DEV_USER_ENABLED` 时可用。这**不代表系统已具备认证能力**。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class UserOrigin(StrEnum):
    """身份来源。用于审计与断言，不能作为授权依据。"""

    development_identity = "development_identity"
    authenticated = "authenticated"


@dataclass(frozen=True, slots=True)
class UserContext:
    """当前请求的用户上下文。

    Attributes:
        user_id: 内部数据库主键（`users.id`），仓储层用它做数据隔离。
        public_id: 对外标识（UUID），用于日志与将来的对外接口，不暴露自增顺序。
        origin: 身份来源。`development_identity` 表示开发注入，不是认证结果。
    """

    user_id: int
    public_id: uuid.UUID
    origin: UserOrigin = UserOrigin.development_identity

    def __post_init__(self) -> None:
        # 防御性校验：user_id 必须是正整数，否则说明上游解析出了问题。
        # 放在这里而不是靠类型注解 —— 注解在运行时不生效。
        if not isinstance(self.user_id, int) or isinstance(self.user_id, bool) or self.user_id <= 0:
            raise ValueError(f"UserContext.user_id 必须是正整数，收到 {self.user_id!r}")
        if not isinstance(self.public_id, uuid.UUID):
            raise TypeError("UserContext.public_id 必须是 uuid.UUID")

    @property
    def is_development_identity(self) -> bool:
        return self.origin is UserOrigin.development_identity

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<UserContext user_id={self.user_id} origin={self.origin.value}>"
