"""JWT 登录用户和 RBAC 权限依赖。"""

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.modules.system import crud
from app.modules.system.model import User


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer Token，并返回当前有效用户。"""

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录令牌无效或已过期") from None
    user = crud.get_user(db, user_id)
    if user is None or user.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    return user


def require_permission(permission_code: str) -> Callable:
    """生成一个校验指定权限编码的 FastAPI 依赖。"""

    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        role_codes = crud.get_user_role_codes(db, current_user.id)
        if "SYS_ADMIN" in role_codes:
            return current_user
        permission_codes = crud.get_user_permission_codes(db, current_user.id)
        if permission_code not in permission_codes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有执行该操作的权限")
        return current_user

    return dependency
