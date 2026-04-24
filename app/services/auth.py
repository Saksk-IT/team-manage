"""
认证服务
处理管理员登录、密码验证和 Session 管理
"""
import logging
import bcrypt
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting, AdminUser
from app.config import settings
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class AuthService:
    """认证服务类"""

    def __init__(self):
        """初始化认证服务"""
        pass

    def hash_password(self, password: str) -> str:
        """
        哈希密码

        Args:
            password: 明文密码

        Returns:
            哈希后的密码
        """
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """
        验证密码

        Args:
            password: 明文密码
            hashed_password: 哈希后的密码

        Returns:
            是否匹配
        """
        try:
            password_bytes = password.encode('utf-8')
            hashed_bytes = hashed_password.encode('utf-8')
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except Exception as e:
            logger.error(f"密码验证失败: {e}")
            return False


    def _normalize_username(self, username: str) -> str:
        return (username or "").strip().lower()

    async def verify_sub_admin_login(
        self,
        username: str,
        password: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        normalized_username = self._normalize_username(username)
        if not normalized_username:
            return {"success": False, "error": "请输入用户名"}

        stmt = select(AdminUser).where(AdminUser.username == normalized_username)
        result = await db_session.execute(stmt)
        admin_user = result.scalar_one_or_none()

        if not admin_user or not admin_user.is_active:
            return {"success": False, "error": "用户不存在或已禁用"}

        if not self.verify_password(password, admin_user.password_hash):
            return {"success": False, "error": "用户名或密码错误"}

        return {
            "success": True,
            "user": {
                "id": admin_user.id,
                "username": admin_user.username,
                "is_admin": True,
                "role": admin_user.role or "import_admin",
                "is_super_admin": False,
            },
            "message": "登录成功",
            "error": None,
        }

    async def create_sub_admin(
        self,
        username: str,
        password: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        normalized_username = self._normalize_username(username)
        if not normalized_username:
            return {"success": False, "error": "用户名不能为空"}
        if normalized_username == "admin":
            return {"success": False, "error": "admin 为总管理员保留用户名"}
        if len(password or "") < 6:
            return {"success": False, "error": "密码长度至少 6 位"}

        existing = await db_session.scalar(select(AdminUser).where(AdminUser.username == normalized_username))
        if existing:
            return {"success": False, "error": "该用户名已存在"}

        now = get_now()
        admin_user = AdminUser(
            username=normalized_username,
            password_hash=self.hash_password(password),
            role="import_admin",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db_session.add(admin_user)
        await db_session.commit()
        return {"success": True, "message": "子管理员已创建", "user_id": admin_user.id}

    async def list_sub_admins(self, db_session: AsyncSession) -> list[dict]:
        result = await db_session.execute(select(AdminUser).order_by(AdminUser.created_at.desc()))
        return [
            {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "is_active": bool(user.is_active),
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            }
            for user in result.scalars().all()
        ]

    async def toggle_sub_admin(
        self,
        user_id: int,
        is_active: bool,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        admin_user = await db_session.get(AdminUser, user_id)
        if not admin_user:
            return {"success": False, "error": "子管理员不存在"}
        admin_user.is_active = bool(is_active)
        admin_user.updated_at = get_now()
        await db_session.commit()
        return {"success": True, "message": "状态已更新"}

    async def reset_sub_admin_password(
        self,
        user_id: int,
        password: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        if len(password or "") < 6:
            return {"success": False, "error": "密码长度至少 6 位"}
        admin_user = await db_session.get(AdminUser, user_id)
        if not admin_user:
            return {"success": False, "error": "子管理员不存在"}
        admin_user.password_hash = self.hash_password(password)
        admin_user.updated_at = get_now()
        await db_session.commit()
        return {"success": True, "message": "密码已重置"}

    async def get_admin_password_hash(self, db_session: AsyncSession) -> Optional[str]:
        """
        从数据库获取管理员密码哈希

        Args:
            db_session: 数据库会话

        Returns:
            密码哈希，如果不存在则返回 None
        """
        try:
            stmt = select(Setting).where(Setting.key == "admin_password_hash")
            result = await db_session.execute(stmt)
            setting = result.scalar_one_or_none()

            if setting:
                return setting.value
            return None

        except Exception as e:
            logger.error(f"获取管理员密码哈希失败: {e}")
            return None

    async def set_admin_password_hash(
        self,
        password_hash: str,
        db_session: AsyncSession
    ) -> bool:
        """
        设置管理员密码哈希到数据库

        Args:
            password_hash: 密码哈希
            db_session: 数据库会话

        Returns:
            是否成功
        """
        try:
            # 查询是否已存在
            stmt = select(Setting).where(Setting.key == "admin_password_hash")
            result = await db_session.execute(stmt)
            setting = result.scalar_one_or_none()

            if setting:
                # 更新
                setting.value = password_hash
            else:
                # 创建
                setting = Setting(
                    key="admin_password_hash",
                    value=password_hash,
                    description="管理员密码哈希"
                )
                db_session.add(setting)

            await db_session.commit()
            logger.info("管理员密码哈希已更新")
            return True

        except Exception as e:
            await db_session.rollback()
            logger.error(f"设置管理员密码哈希失败: {e}")
            return False

    async def initialize_admin_password(self, db_session: AsyncSession) -> bool:
        """
        初始化管理员密码
        如果数据库中没有密码哈希，则从配置文件读取并哈希后存储

        Args:
            db_session: 数据库会话

        Returns:
            是否成功
        """
        try:
            # 检查是否已存在
            existing_hash = await self.get_admin_password_hash(db_session)

            if existing_hash:
                logger.info("管理员密码已存在，跳过初始化")
                return True

            # 从配置读取密码
            admin_password = settings.admin_password

            if not admin_password or admin_password == "admin123":
                logger.warning("使用默认密码，建议修改！")

            # 哈希密码
            password_hash = self.hash_password(admin_password)

            # 存储到数据库
            success = await self.set_admin_password_hash(password_hash, db_session)

            if success:
                logger.info("管理员密码初始化成功")
            else:
                logger.error("管理员密码初始化失败")

            return success

        except Exception as e:
            logger.error(f"初始化管理员密码失败: {e}")
            return False

    async def verify_admin_login(
        self,
        password: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        验证管理员登录

        Args:
            password: 密码
            db_session: 数据库会话

        Returns:
            结果字典，包含 success, message, error
        """
        try:
            # 获取密码哈希
            password_hash = await self.get_admin_password_hash(db_session)

            if not password_hash:
                # 尝试初始化
                await self.initialize_admin_password(db_session)
                password_hash = await self.get_admin_password_hash(db_session)

                if not password_hash:
                    return {
                        "success": False,
                        "message": None,
                        "error": "系统错误：无法获取管理员密码"
                    }

            # 验证密码
            if self.verify_password(password, password_hash):
                logger.info("管理员登录成功")
                return {
                    "success": True,
                    "message": "登录成功",
                    "error": None
                }
            else:
                logger.warning("管理员登录失败：密码错误")
                return {
                    "success": False,
                    "message": None,
                    "error": "密码错误"
                }

        except Exception as e:
            logger.error(f"验证管理员登录失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"登录失败: {str(e)}"
            }

    async def change_admin_password(
        self,
        old_password: str,
        new_password: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        修改管理员密码

        Args:
            old_password: 旧密码
            new_password: 新密码
            db_session: 数据库会话

        Returns:
            结果字典，包含 success, message, error
        """
        try:
            # 验证旧密码
            verify_result = await self.verify_admin_login(old_password, db_session)

            if not verify_result["success"]:
                return {
                    "success": False,
                    "message": None,
                    "error": "旧密码错误"
                }

            # 哈希新密码
            new_password_hash = self.hash_password(new_password)

            # 更新密码
            success = await self.set_admin_password_hash(new_password_hash, db_session)

            if success:
                logger.info("管理员密码修改成功")
                return {
                    "success": True,
                    "message": "密码修改成功",
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "message": None,
                    "error": "密码修改失败"
                }

        except Exception as e:
            logger.error(f"修改管理员密码失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"密码修改失败: {str(e)}"
            }


# 创建全局实例
auth_service = AuthService()
