"""
认证依赖
用于保护需要认证的路由
"""
import logging
from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)

ROLE_SUPER_ADMIN = "super_admin"
ROLE_IMPORT_ADMIN = "import_admin"


def get_current_user(request: Request) -> dict:
    """获取当前登录用户。"""
    user = request.session.get("user")

    if not user:
        logger.warning("未登录用户尝试访问受保护资源")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录"
        )

    return user


def is_super_admin_user(user: dict | None) -> bool:
    return bool(user and user.get("is_admin") and user.get("is_super_admin", user.get("role") == ROLE_SUPER_ADMIN))


def is_import_admin_user(user: dict | None) -> bool:
    return bool(user and user.get("is_admin") and user.get("role") == ROLE_IMPORT_ADMIN)


async def _api_key_super_admin(request: Request) -> dict | None:
    api_key_header = request.headers.get("X-API-Key")
    if not api_key_header:
        return None

    from app.database import AsyncSessionLocal
    from app.services.settings import settings_service

    async with AsyncSessionLocal() as db:
        api_key = await settings_service.get_setting(db, "api_key")
        if api_key and api_key_header == api_key:
            return {
                "username": "api_user",
                "is_admin": True,
                "role": ROLE_SUPER_ADMIN,
                "is_super_admin": True,
            }
    return None


async def require_admin(request: Request) -> dict:
    """要求总管理员权限；API Key 也视为总管理员。"""
    user = request.session.get("user")
    if is_super_admin_user(user):
        return user

    api_user = await _api_key_super_admin(request)
    if api_user:
        return api_user

    logger.warning("认证失败: 需要总管理员权限")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="需要总管理员权限"
    )


async def require_team_import_admin(request: Request) -> dict:
    """允许总管理员或子管理员访问 Team 导入能力。"""
    user = request.session.get("user")
    if is_super_admin_user(user) or is_import_admin_user(user):
        return user

    api_user = await _api_key_super_admin(request)
    if api_user:
        return api_user

    logger.warning("认证失败: 需要导入权限")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或无导入权限"
    )


def optional_user(request: Request) -> dict | None:
    """可选的用户信息。"""
    return request.session.get("user")
