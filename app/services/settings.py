"""
系统设置服务
管理系统配置的读取、更新和缓存
"""
import secrets
import string
from typing import Optional, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Setting
from app.utils.storage import is_customer_service_upload_url, resolve_customer_service_upload_display_url
import logging

logger = logging.getLogger(__name__)


class SettingsService:
    """系统设置服务类"""

    DEFAULT_TEAM_MAX_MEMBERS_KEY = "default_team_max_members"
    FRONT_ANNOUNCEMENT_ENABLED_KEY = "front_announcement_enabled"
    FRONT_ANNOUNCEMENT_CONTENT_KEY = "front_announcement_content"
    CUSTOMER_SERVICE_ENABLED_KEY = "customer_service_enabled"
    CUSTOMER_SERVICE_QR_CODE_URL_KEY = "customer_service_qr_code_url"
    CUSTOMER_SERVICE_LINK_URL_KEY = "customer_service_link_url"
    CUSTOMER_SERVICE_LINK_TEXT_KEY = "customer_service_link_text"
    CUSTOMER_SERVICE_TEXT_KEY = "customer_service_text"
    PURCHASE_LINK_ENABLED_KEY = "purchase_link_enabled"
    PURCHASE_LINK_URL_KEY = "purchase_link_url"
    PURCHASE_LINK_BUTTON_TEXT_KEY = "purchase_link_button_text"
    WARRANTY_SERVICE_ENABLED_KEY = "warranty_service_enabled"
    WARRANTY_USAGE_LIMIT_SUPER_CODE_KEY = "warranty_usage_limit_super_code"
    WARRANTY_USAGE_LIMIT_MAX_USES_KEY = "warranty_usage_limit_max_uses"
    WARRANTY_TIME_LIMIT_SUPER_CODE_KEY = "warranty_time_limit_super_code"
    WARRANTY_TIME_LIMIT_DAYS_KEY = "warranty_time_limit_days"
    WARRANTY_FAKE_SUCCESS_ENABLED_KEY = "warranty_fake_success_enabled"
    WARRANTY_FAKE_SUCCESS_REMAINING_SPOTS_KEY = "warranty_fake_success_remaining_spots"
    WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT = "usage_limit"
    WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT = "time_limit"
    DEFAULT_WARRANTY_SERVICE_ENABLED = True
    DEFAULT_WARRANTY_FAKE_SUCCESS_ENABLED = False
    DEFAULT_TEAM_MAX_MEMBERS = 5
    DEFAULT_FRONT_ANNOUNCEMENT_ENABLED = False
    DEFAULT_CUSTOMER_SERVICE_ENABLED = False
    DEFAULT_PURCHASE_LINK_ENABLED = False
    WARRANTY_FAKE_SUCCESS_MIN_SPOTS = 60
    WARRANTY_FAKE_SUCCESS_MAX_SPOTS = 100
    TEAM_AUTO_REFRESH_ENABLED_KEY = "team_auto_refresh_enabled"
    TEAM_AUTO_REFRESH_INTERVAL_MINUTES_KEY = "team_auto_refresh_interval_minutes"
    DEFAULT_TEAM_AUTO_REFRESH_ENABLED = True
    DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES = 5
    MIN_TEAM_AUTO_REFRESH_INTERVAL_MINUTES = 1
    MAX_TEAM_AUTO_REFRESH_INTERVAL_MINUTES = 1440

    def __init__(self):
        self._cache: Dict[str, str] = {}

    async def get_setting(self, session: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        获取单个配置项

        Args:
            session: 数据库会话
            key: 配置项键名
            default: 默认值

        Returns:
            配置项值,如果不存在则返回默认值
        """
        # 先从缓存获取
        if key in self._cache:
            return self._cache[key]

        # 从数据库获取
        result = await session.execute(
            select(Setting).where(Setting.key == key)
        )
        setting = result.scalar_one_or_none()

        if setting:
            self._cache[key] = setting.value
            return setting.value

        return default

    async def get_all_settings(self, session: AsyncSession) -> Dict[str, str]:
        """
        获取所有配置项

        Args:
            session: 数据库会话

        Returns:
            配置项字典
        """
        result = await session.execute(select(Setting))
        settings = result.scalars().all()

        settings_dict = {s.key: s.value for s in settings}
        self._cache.update(settings_dict)

        return settings_dict

    async def update_setting(self, session: AsyncSession, key: str, value: str) -> bool:
        """
        更新单个配置项

        Args:
            session: 数据库会话
            key: 配置项键名
            value: 配置项值

        Returns:
            是否更新成功
        """
        try:
            result = await session.execute(
                select(Setting).where(Setting.key == key)
            )
            setting = result.scalar_one_or_none()

            if setting:
                setting.value = value
            else:
                setting = Setting(key=key, value=value)
                session.add(setting)

            await session.commit()

            # 更新缓存
            self._cache[key] = value

            logger.info(f"配置项 {key} 已更新")
            return True

        except Exception as e:
            logger.error(f"更新配置项 {key} 失败: {e}")
            await session.rollback()
            return False

    async def update_settings(self, session: AsyncSession, settings: Dict[str, str]) -> bool:
        """
        批量更新配置项

        Args:
            session: 数据库会话
            settings: 配置项字典

        Returns:
            是否更新成功
        """
        try:
            for key, value in settings.items():
                result = await session.execute(
                    select(Setting).where(Setting.key == key)
                )
                setting = result.scalar_one_or_none()

                if setting:
                    setting.value = value
                else:
                    setting = Setting(key=key, value=value)
                    session.add(setting)

            await session.commit()

            # 更新缓存
            self._cache.update(settings)

            logger.info(f"批量更新了 {len(settings)} 个配置项")
            return True

        except Exception as e:
            logger.error(f"批量更新配置项失败: {e}")
            await session.rollback()
            return False

    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.info("配置缓存已清空")

    def _parse_bool(self, value: Optional[str], default: bool = False) -> bool:
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _parse_int(self, value: Optional[str], default: int) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError, AttributeError):
            return default

    async def get_front_announcement_config(self, session: AsyncSession) -> Dict[str, str | bool]:
        """
        获取前台公告配置。
        """
        enabled_raw = await self.get_setting(
            session,
            self.FRONT_ANNOUNCEMENT_ENABLED_KEY,
            str(self.DEFAULT_FRONT_ANNOUNCEMENT_ENABLED).lower()
        )
        content = await self.get_setting(
            session,
            self.FRONT_ANNOUNCEMENT_CONTENT_KEY,
            ""
        )
        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_FRONT_ANNOUNCEMENT_ENABLED
            ),
            "content": (content or "").strip()
        }

    async def update_front_announcement_config(
        self,
        session: AsyncSession,
        enabled: bool,
        content: str = ""
    ) -> bool:
        """
        更新前台公告配置。
        """
        return await self.update_settings(
            session,
            {
                self.FRONT_ANNOUNCEMENT_ENABLED_KEY: str(bool(enabled)).lower(),
                self.FRONT_ANNOUNCEMENT_CONTENT_KEY: (content or "").strip()
            }
        )

    async def get_customer_service_config(self, session: AsyncSession) -> Dict[str, str | bool]:
        """
        获取前台客服配置。
        """
        enabled_raw = await self.get_setting(
            session,
            self.CUSTOMER_SERVICE_ENABLED_KEY,
            str(self.DEFAULT_CUSTOMER_SERVICE_ENABLED).lower()
        )
        qr_code_url = await self.get_setting(
            session,
            self.CUSTOMER_SERVICE_QR_CODE_URL_KEY,
            ""
        )
        link_url = await self.get_setting(
            session,
            self.CUSTOMER_SERVICE_LINK_URL_KEY,
            ""
        )
        link_text = await self.get_setting(
            session,
            self.CUSTOMER_SERVICE_LINK_TEXT_KEY,
            ""
        )
        text_content = await self.get_setting(
            session,
            self.CUSTOMER_SERVICE_TEXT_KEY,
            ""
        )
        normalized_qr_code_url = (qr_code_url or "").strip()
        if is_customer_service_upload_url(normalized_qr_code_url):
            normalized_qr_code_url = resolve_customer_service_upload_display_url(normalized_qr_code_url)
            if not normalized_qr_code_url:
                logger.warning("客服二维码图片路径不存在，已跳过展示")
        normalized_link_url = (link_url or "").strip()
        normalized_link_text = (link_text or "").strip()

        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_CUSTOMER_SERVICE_ENABLED
            ),
            "qr_code_url": normalized_qr_code_url,
            "link_url": normalized_link_url,
            "link_text": normalized_link_text or ("立即联系" if normalized_link_url else ""),
            "text_content": (text_content or "").strip()
        }

    async def update_customer_service_config(
        self,
        session: AsyncSession,
        enabled: bool,
        qr_code_url: str = "",
        link_url: str = "",
        link_text: str = "",
        text_content: str = ""
    ) -> bool:
        """
        更新前台客服配置。
        """
        normalized_link_url = (link_url or "").strip()
        normalized_link_text = (link_text or "").strip()

        return await self.update_settings(
            session,
            {
                self.CUSTOMER_SERVICE_ENABLED_KEY: str(bool(enabled)).lower(),
                self.CUSTOMER_SERVICE_QR_CODE_URL_KEY: (qr_code_url or "").strip(),
                self.CUSTOMER_SERVICE_LINK_URL_KEY: normalized_link_url,
                self.CUSTOMER_SERVICE_LINK_TEXT_KEY: normalized_link_text or ("立即联系" if normalized_link_url else ""),
                self.CUSTOMER_SERVICE_TEXT_KEY: (text_content or "").strip()
            }
        )

    async def get_purchase_link_config(self, session: AsyncSession) -> Dict[str, str | bool]:
        """
        获取前台商品购买链接配置。
        """
        enabled_raw = await self.get_setting(
            session,
            self.PURCHASE_LINK_ENABLED_KEY,
            str(self.DEFAULT_PURCHASE_LINK_ENABLED).lower()
        )
        url = await self.get_setting(session, self.PURCHASE_LINK_URL_KEY, "")
        button_text = await self.get_setting(session, self.PURCHASE_LINK_BUTTON_TEXT_KEY, "")

        normalized_url = (url or "").strip()
        normalized_button_text = (button_text or "").strip()

        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_PURCHASE_LINK_ENABLED
            ),
            "url": normalized_url,
            "button_text": normalized_button_text or ("立即购买" if normalized_url else "")
        }

    async def update_purchase_link_config(
        self,
        session: AsyncSession,
        enabled: bool,
        url: str = "",
        button_text: str = ""
    ) -> bool:
        """
        更新前台商品购买链接配置。
        """
        normalized_url = (url or "").strip()
        normalized_button_text = (button_text or "").strip()

        return await self.update_settings(
            session,
            {
                self.PURCHASE_LINK_ENABLED_KEY: str(bool(enabled)).lower(),
                self.PURCHASE_LINK_URL_KEY: normalized_url,
                self.PURCHASE_LINK_BUTTON_TEXT_KEY: normalized_button_text or ("立即购买" if normalized_url else "")
            }
        )

    async def get_team_auto_refresh_config(self, session: AsyncSession) -> Dict[str, int | bool]:
        """
        获取 Team 自动刷新配置。
        """
        enabled_raw = await self.get_setting(
            session,
            self.TEAM_AUTO_REFRESH_ENABLED_KEY,
            str(self.DEFAULT_TEAM_AUTO_REFRESH_ENABLED).lower()
        )
        interval_raw = await self.get_setting(
            session,
            self.TEAM_AUTO_REFRESH_INTERVAL_MINUTES_KEY,
            str(self.DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES)
        )

        interval_minutes = self._parse_int(
            interval_raw,
            self.DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES
        )
        if interval_minutes < self.MIN_TEAM_AUTO_REFRESH_INTERVAL_MINUTES or interval_minutes > self.MAX_TEAM_AUTO_REFRESH_INTERVAL_MINUTES:
            interval_minutes = self.DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES

        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_TEAM_AUTO_REFRESH_ENABLED
            ),
            "interval_minutes": interval_minutes
        }

    async def update_team_auto_refresh_config(
        self,
        session: AsyncSession,
        enabled: bool,
        interval_minutes: int
    ) -> bool:
        """
        更新 Team 自动刷新配置。
        """
        if interval_minutes < self.MIN_TEAM_AUTO_REFRESH_INTERVAL_MINUTES or interval_minutes > self.MAX_TEAM_AUTO_REFRESH_INTERVAL_MINUTES:
            raise ValueError(
                f"自动刷新间隔必须在 {self.MIN_TEAM_AUTO_REFRESH_INTERVAL_MINUTES} 到 {self.MAX_TEAM_AUTO_REFRESH_INTERVAL_MINUTES} 分钟之间"
            )

        return await self.update_settings(
            session,
            {
                self.TEAM_AUTO_REFRESH_ENABLED_KEY: str(bool(enabled)).lower(),
                self.TEAM_AUTO_REFRESH_INTERVAL_MINUTES_KEY: str(interval_minutes)
            }
        )

    async def get_default_team_max_members(self, session: AsyncSession) -> int:
        """
        获取每个 Team 的默认最大人数。
        """
        value_raw = await self.get_setting(
            session,
            self.DEFAULT_TEAM_MAX_MEMBERS_KEY,
            str(self.DEFAULT_TEAM_MAX_MEMBERS)
        )
        value = self._parse_int(value_raw, self.DEFAULT_TEAM_MAX_MEMBERS)
        return value if value > 0 else self.DEFAULT_TEAM_MAX_MEMBERS

    async def update_default_team_max_members(
        self,
        session: AsyncSession,
        value: int
    ) -> bool:
        """
        更新每个 Team 的默认最大人数。
        """
        try:
            normalized_value = int(value)
        except (TypeError, ValueError):
            raise ValueError("每个 Team 默认最大人数必须为正整数")

        if normalized_value <= 0:
            raise ValueError("每个 Team 默认最大人数必须大于 0")

        return await self.update_setting(
            session,
            self.DEFAULT_TEAM_MAX_MEMBERS_KEY,
            str(normalized_value)
        )

    async def get_warranty_service_config(self, session: AsyncSession) -> Dict[str, bool]:
        """
        获取前台质保服务开关配置。
        """
        enabled_raw = await self.get_setting(
            session,
            self.WARRANTY_SERVICE_ENABLED_KEY,
            str(self.DEFAULT_WARRANTY_SERVICE_ENABLED).lower()
        )
        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_WARRANTY_SERVICE_ENABLED
            )
        }

    async def update_warranty_service_config(
        self,
        session: AsyncSession,
        enabled: bool
    ) -> bool:
        """
        更新前台质保服务开关配置。
        """
        return await self.update_setting(
            session,
            self.WARRANTY_SERVICE_ENABLED_KEY,
            str(bool(enabled)).lower()
        )

    async def get_warranty_fake_success_config(self, session: AsyncSession) -> Dict[str, bool]:
        """
        获取前台质保模拟成功开关配置。
        """
        enabled_raw = await self.get_setting(
            session,
            self.WARRANTY_FAKE_SUCCESS_ENABLED_KEY,
            str(self.DEFAULT_WARRANTY_FAKE_SUCCESS_ENABLED).lower()
        )
        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_WARRANTY_FAKE_SUCCESS_ENABLED
            )
        }

    async def update_warranty_fake_success_config(
        self,
        session: AsyncSession,
        enabled: bool
    ) -> bool:
        """
        更新前台质保模拟成功开关配置。
        """
        success = await self.update_setting(
            session,
            self.WARRANTY_FAKE_SUCCESS_ENABLED_KEY,
            str(bool(enabled)).lower()
        )
        if not success:
            return False

        if enabled:
            try:
                await self.get_warranty_fake_success_remaining_spots(session)
            except Exception as e:
                logger.error(f"初始化前台质保模拟席位失败: {e}")
                return False

        return True

    def _parse_warranty_fake_success_remaining_spots(self, value: Optional[str]) -> Optional[int]:
        parsed_value = self._parse_int(value, -1)
        if self.WARRANTY_FAKE_SUCCESS_MIN_SPOTS <= parsed_value <= self.WARRANTY_FAKE_SUCCESS_MAX_SPOTS:
            return parsed_value
        return None

    def _generate_warranty_fake_success_remaining_spots(self) -> int:
        span = self.WARRANTY_FAKE_SUCCESS_MAX_SPOTS - self.WARRANTY_FAKE_SUCCESS_MIN_SPOTS + 1
        return self.WARRANTY_FAKE_SUCCESS_MIN_SPOTS + secrets.randbelow(span)

    async def get_warranty_fake_success_remaining_spots(self, session: AsyncSession) -> int:
        """
        获取前台质保模拟成功模式下的持久化席位数。
        若不存在或越界，则自动初始化到 60~100 的随机值。
        """
        remaining_spots_raw = await self.get_setting(
            session,
            self.WARRANTY_FAKE_SUCCESS_REMAINING_SPOTS_KEY,
            ""
        )
        remaining_spots = self._parse_warranty_fake_success_remaining_spots(remaining_spots_raw)
        if remaining_spots is not None:
            return remaining_spots

        generated_spots = self._generate_warranty_fake_success_remaining_spots()
        success = await self.update_setting(
            session,
            self.WARRANTY_FAKE_SUCCESS_REMAINING_SPOTS_KEY,
            str(generated_spots)
        )
        if not success:
            raise RuntimeError("初始化前台质保模拟席位失败")
        return generated_spots

    async def decrement_warranty_fake_success_remaining_spots(self, session: AsyncSession) -> int:
        """
        质保模拟成功后扣减展示席位，但不会低于 60。
        """
        current_spots = await self.get_warranty_fake_success_remaining_spots(session)
        next_spots = max(current_spots - 1, self.WARRANTY_FAKE_SUCCESS_MIN_SPOTS)

        if next_spots == current_spots:
            return current_spots

        success = await self.update_setting(
            session,
            self.WARRANTY_FAKE_SUCCESS_REMAINING_SPOTS_KEY,
            str(next_spots)
        )
        if not success:
            raise RuntimeError("扣减前台质保模拟席位失败")
        return next_spots

    async def get_proxy_config(self, session: AsyncSession) -> Dict[str, str]:
        """
        获取代理配置

        Returns:
            代理配置字典
        """
        proxy_enabled = await self.get_setting(session, "proxy_enabled", "false")
        proxy = await self.get_setting(session, "proxy", "")

        return {
            "enabled": str(proxy_enabled).lower() == "true",
            "proxy": proxy
        }

    async def update_proxy_config(
        self,
        session: AsyncSession,
        enabled: bool,
        proxy: str = ""
    ) -> bool:
        """
        更新代理配置

        Args:
            session: 数据库会话
            enabled: 是否启用代理
            proxy: 代理地址 (格式: http://host:port 或 socks5://host:port)

        Returns:
            是否更新成功
        """
        settings = {
            "proxy_enabled": str(enabled).lower(),
            "proxy": proxy
        }

        return await self.update_settings(session, settings)

    async def get_log_level(self, session: AsyncSession) -> str:
        """
        获取日志级别

        Returns:
            日志级别
        """
        return await self.get_setting(session, "log_level", "INFO")

    async def update_log_level(self, session: AsyncSession, level: str) -> bool:
        """
        更新日志级别

        Args:
            session: 数据库会话
            level: 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)

        Returns:
            是否更新成功
        """
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if level.upper() not in valid_levels:
            logger.error(f"无效的日志级别: {level}")
            return False

        success = await self.update_setting(session, "log_level", level.upper())

        if success:
            # 动态更新日志级别
            logging.getLogger().setLevel(level.upper())
            logger.info(f"日志级别已更新为: {level.upper()}")

        return success

    def _generate_warranty_super_code(self, length: int = 20) -> str:
        alphabet = string.ascii_uppercase + string.digits
        alphabet = alphabet.replace('0', '').replace('O', '').replace('I', '').replace('1', '')
        raw = ''.join(secrets.choice(alphabet) for _ in range(length))
        return '-'.join(raw[i:i + 4] for i in range(0, len(raw), 4))

    def _normalize_super_code(self, code: str) -> str:
        return (code or "").strip().upper()

    def _get_warranty_super_code_meta(self, code_type: str) -> Dict[str, str]:
        if code_type == self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT:
            return {
                "code_key": self.WARRANTY_USAGE_LIMIT_SUPER_CODE_KEY,
                "limit_key": self.WARRANTY_USAGE_LIMIT_MAX_USES_KEY,
                "limit_name": "max_uses",
                "default_limit": 2
            }
        if code_type == self.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT:
            return {
                "code_key": self.WARRANTY_TIME_LIMIT_SUPER_CODE_KEY,
                "limit_key": self.WARRANTY_TIME_LIMIT_DAYS_KEY,
                "limit_name": "days",
                "default_limit": 15
            }
        raise ValueError("无效的超级兑换码类型")

    async def get_warranty_super_code_configs(self, session: AsyncSession) -> Dict[str, Dict[str, Optional[str]]]:
        usage_code = self._normalize_super_code(
            await self.get_setting(session, self.WARRANTY_USAGE_LIMIT_SUPER_CODE_KEY, "") or ""
        )
        usage_limit_raw = await self.get_setting(session, self.WARRANTY_USAGE_LIMIT_MAX_USES_KEY, "")
        time_code = self._normalize_super_code(
            await self.get_setting(session, self.WARRANTY_TIME_LIMIT_SUPER_CODE_KEY, "") or ""
        )
        time_limit_raw = await self.get_setting(session, self.WARRANTY_TIME_LIMIT_DAYS_KEY, "")

        usage_limit_str = str(usage_limit_raw).strip()
        time_limit_str = str(time_limit_raw).strip()
        usage_limit = int(usage_limit_str) if usage_limit_str.isdigit() else None
        time_limit = int(time_limit_str) if time_limit_str.isdigit() else None

        return {
            self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT: {
                "code": usage_code,
                "max_uses": usage_limit,
                "enabled": bool(usage_code)
            },
            self.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT: {
                "code": time_code,
                "days": time_limit,
                "enabled": bool(time_code)
            }
        }

    async def save_warranty_super_code_config(
        self,
        session: AsyncSession,
        code_type: str,
        code: str,
        limit_value: int
    ) -> Dict[str, Optional[str]]:
        meta = self._get_warranty_super_code_meta(code_type)
        normalized_code = self._normalize_super_code(code)
        if not normalized_code:
            raise ValueError("超级兑换码不能为空")

        try:
            limit_int = int(limit_value)
        except (TypeError, ValueError):
            raise ValueError("限制值必须为正整数")

        if limit_int <= 0:
            raise ValueError("限制值必须大于 0")

        configs = await self.get_warranty_super_code_configs(session)
        other_type = (
            self.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT
            if code_type == self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT
            else self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT
        )
        other_code = configs[other_type]["code"]
        if other_code and other_code == normalized_code:
            raise ValueError("两类超级兑换码不能配置为相同值")

        success = await self.update_settings(
            session,
            {
                meta["code_key"]: normalized_code,
                meta["limit_key"]: str(limit_int)
            }
        )
        if not success:
            raise RuntimeError("保存超级兑换码失败")

        return {
            "code": normalized_code,
            meta["limit_name"]: limit_int,
            "enabled": True
        }

    async def disable_warranty_super_code_config(self, session: AsyncSession, code_type: str) -> None:
        meta = self._get_warranty_super_code_meta(code_type)
        success = await self.update_settings(
            session,
            {
                meta["code_key"]: "",
                meta["limit_key"]: ""
            }
        )
        if not success:
            raise RuntimeError("停用超级兑换码失败")

    async def regenerate_warranty_super_code(
        self,
        session: AsyncSession,
        code_type: str,
        limit_value: Optional[int] = None
    ) -> Dict[str, Optional[str]]:
        meta = self._get_warranty_super_code_meta(code_type)
        configs = await self.get_warranty_super_code_configs(session)
        current_limit = configs[code_type].get(meta["limit_name"])
        final_limit = limit_value if limit_value is not None else current_limit or meta["default_limit"]

        other_type = (
            self.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT
            if code_type == self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT
            else self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT
        )
        other_code = configs[other_type]["code"]

        for _ in range(10):
            generated_code = self._generate_warranty_super_code()
            if other_code and generated_code == other_code:
                continue
            return await self.save_warranty_super_code_config(session, code_type, generated_code, final_limit)

        raise RuntimeError("生成唯一超级兑换码失败")

    async def match_warranty_super_code(
        self,
        session: AsyncSession,
        code: str
    ) -> Optional[Dict[str, Optional[str]]]:
        normalized_code = self._normalize_super_code(code)
        if not normalized_code:
            return None

        configs = await self.get_warranty_super_code_configs(session)
        usage_config = configs[self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT]
        if usage_config["enabled"] and usage_config["code"] == normalized_code:
            return {
                "type": self.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT,
                "code": usage_config["code"],
                "max_uses": usage_config["max_uses"]
            }

        time_config = configs[self.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT]
        if time_config["enabled"] and time_config["code"] == normalized_code:
            return {
                "type": self.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT,
                "code": time_config["code"],
                "days": time_config["days"]
            }

        return None


# 创建全局实例
settings_service = SettingsService()
