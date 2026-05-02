"""
系统设置服务
管理系统配置的读取、更新和缓存
"""
import json
import secrets
import string
from typing import Any, Optional, Dict, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Setting
from app.services.admin_sidebar import (
    get_default_admin_sidebar_order,
    normalize_admin_sidebar_order,
)
from app.utils.storage import is_customer_service_upload_url, resolve_customer_service_upload_display_url
from app.utils.rich_text import sanitize_rich_text
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
    WARRANTY_EMAIL_CHECK_ENABLED_KEY = "warranty_email_check_enabled"
    WARRANTY_EMAIL_CHECK_MATCH_CONTENT_KEY = "warranty_email_check_match_content"
    WARRANTY_EMAIL_CHECK_MISS_CONTENT_KEY = "warranty_email_check_miss_content"
    WARRANTY_EMAIL_CHECK_MATCH_TEMPLATES_KEY = "warranty_email_check_match_templates"
    WARRANTY_EMAIL_CHECK_MISS_TEMPLATES_KEY = "warranty_email_check_miss_templates"
    WARRANTY_EMAIL_CHECK_SHOW_STATIC_TUTORIAL_KEY = "warranty_email_check_show_static_tutorial"
    SUB2API_WARRANTY_BASE_URL_KEY = "sub2api_warranty_base_url"
    SUB2API_WARRANTY_ADMIN_API_KEY_KEY = "sub2api_warranty_admin_api_key"
    SUB2API_WARRANTY_SUBSCRIPTION_GROUP_ID_KEY = "sub2api_warranty_subscription_group_id"
    SUB2API_WARRANTY_CODE_PREFIX_KEY = "sub2api_warranty_code_prefix"
    ADMIN_SIDEBAR_ORDER_KEY = "admin_sidebar_order"
    NUMBER_POOL_ENABLED_KEY = "number_pool_enabled"
    WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT = "usage_limit"
    WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT = "time_limit"
    DEFAULT_WARRANTY_SERVICE_ENABLED = True
    DEFAULT_WARRANTY_FAKE_SUCCESS_ENABLED = False
    DEFAULT_WARRANTY_EMAIL_CHECK_ENABLED = False
    DEFAULT_WARRANTY_EMAIL_CHECK_SHOW_STATIC_TUTORIAL = False
    DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_CONTENT = "<p>该邮箱已在质保邮箱列表内，请按页面提示继续处理。</p>"
    DEFAULT_WARRANTY_EMAIL_CHECK_MISS_CONTENT = "<p>未查询到该邮箱的质保记录，请核对邮箱或联系管理员处理。</p>"
    DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_TEMPLATE_NAME = "命中模板 1"
    DEFAULT_WARRANTY_EMAIL_CHECK_MISS_TEMPLATE_NAME = "未命中模板 1"
    DEFAULT_SUB2API_WARRANTY_CODE_PREFIX = "TMW"
    DEFAULT_TEAM_MAX_MEMBERS = 5
    DEFAULT_NUMBER_POOL_ENABLED = False
    DEFAULT_FRONT_ANNOUNCEMENT_ENABLED = False
    DEFAULT_CUSTOMER_SERVICE_ENABLED = False
    DEFAULT_PURCHASE_LINK_ENABLED = False
    WARRANTY_FAKE_SUCCESS_MIN_SPOTS = 60
    WARRANTY_FAKE_SUCCESS_MAX_SPOTS = 100
    TEAM_AUTO_REFRESH_ENABLED_KEY = "team_auto_refresh_enabled"
    TEAM_AUTO_REFRESH_INTERVAL_MINUTES_KEY = "team_auto_refresh_interval_minutes"
    WARRANTY_EXPIRY_AUTO_CLEANUP_ENABLED_KEY = "warranty_expiry_auto_cleanup_enabled"
    DEFAULT_TEAM_AUTO_REFRESH_ENABLED = True
    DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES = 5
    DEFAULT_WARRANTY_EXPIRY_AUTO_CLEANUP_ENABLED = False
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

    def _build_warranty_email_check_template(
        self,
        template_id: str,
        name: str,
        content: str,
    ) -> Dict[str, str]:
        return {
            "id": (template_id or "").strip(),
            "name": (name or "").strip(),
            "content": content or "",
        }

    def _get_default_warranty_email_check_templates(self, matched: bool) -> list[Dict[str, str]]:
        return [
            self._build_warranty_email_check_template(
                "match-default" if matched else "miss-default",
                self.DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_TEMPLATE_NAME
                if matched
                else self.DEFAULT_WARRANTY_EMAIL_CHECK_MISS_TEMPLATE_NAME,
                self.DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_CONTENT
                if matched
                else self.DEFAULT_WARRANTY_EMAIL_CHECK_MISS_CONTENT,
            )
        ]

    def _normalize_warranty_email_check_templates(
        self,
        templates: Sequence[Dict[str, Any]] | None,
        matched: bool,
    ) -> list[Dict[str, str]]:
        normalized_templates: list[Dict[str, str]] = []
        used_ids: set[str] = set()
        prefix = "match" if matched else "miss"

        for index, item in enumerate(templates or [], start=1):
            if not isinstance(item, dict):
                continue

            sanitized_content = sanitize_rich_text(str(item.get("content") or ""))
            if not sanitized_content:
                continue

            raw_id = str(item.get("id") or "").strip()[:80]
            template_id = raw_id or f"{prefix}-{index}"
            if template_id in used_ids:
                template_id = f"{template_id}-{index}"
            used_ids.add(template_id)

            default_name = f"{'命中' if matched else '未命中'}模板 {index}"
            template_name = str(item.get("name") or "").strip()[:80] or default_name
            normalized_templates.append(
                self._build_warranty_email_check_template(
                    template_id,
                    template_name,
                    sanitized_content,
                )
            )

        return normalized_templates or self._get_default_warranty_email_check_templates(matched)

    def _parse_warranty_email_check_templates(
        self,
        value: Optional[str],
        matched: bool,
        legacy_content: str,
    ) -> list[Dict[str, str]]:
        try:
            parsed_value = json.loads(value or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_value = []

        templates = parsed_value if isinstance(parsed_value, list) else []
        legacy_template = self._build_warranty_email_check_template(
            "match-default" if matched else "miss-default",
            self.DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_TEMPLATE_NAME
            if matched
            else self.DEFAULT_WARRANTY_EMAIL_CHECK_MISS_TEMPLATE_NAME,
            legacy_content,
        )
        return self._normalize_warranty_email_check_templates(
            templates or [legacy_template],
            matched,
        )

    def get_warranty_email_check_template_content(
        self,
        templates: Sequence[Dict[str, str]],
        template_key: Optional[str],
    ) -> Optional[str]:
        normalized_key = (template_key or "").strip()
        if not normalized_key:
            return None

        for template in templates or []:
            if (template.get("id") or "").strip() == normalized_key:
                return template.get("content") or ""

        return None

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

    async def get_warranty_expiry_auto_cleanup_config(self, session: AsyncSession) -> Dict[str, bool]:
        """获取质保到期自动踢出配置。"""
        enabled_raw = await self.get_setting(
            session,
            self.WARRANTY_EXPIRY_AUTO_CLEANUP_ENABLED_KEY,
            str(self.DEFAULT_WARRANTY_EXPIRY_AUTO_CLEANUP_ENABLED).lower()
        )
        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_WARRANTY_EXPIRY_AUTO_CLEANUP_ENABLED
            )
        }

    async def update_warranty_expiry_auto_cleanup_config(
        self,
        session: AsyncSession,
        enabled: bool
    ) -> bool:
        """更新质保到期自动踢出配置。"""
        return await self.update_setting(
            session,
            self.WARRANTY_EXPIRY_AUTO_CLEANUP_ENABLED_KEY,
            str(bool(enabled)).lower()
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


    async def get_number_pool_config(self, session: AsyncSession) -> Dict[str, bool]:
        """获取独立号池开关配置。"""
        enabled_raw = await self.get_setting(
            session,
            self.NUMBER_POOL_ENABLED_KEY,
            str(self.DEFAULT_NUMBER_POOL_ENABLED).lower()
        )
        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_NUMBER_POOL_ENABLED
            )
        }

    async def update_number_pool_config(
        self,
        session: AsyncSession,
        enabled: bool
    ) -> bool:
        """更新独立号池开关配置。"""
        return await self.update_setting(
            session,
            self.NUMBER_POOL_ENABLED_KEY,
            str(bool(enabled)).lower()
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

    async def get_warranty_email_check_config(self, session: AsyncSession) -> Dict[str, Any]:
        """
        获取前台质保邮箱名单判定模式配置。
        """
        enabled_raw = await self.get_setting(
            session,
            self.WARRANTY_EMAIL_CHECK_ENABLED_KEY,
            str(self.DEFAULT_WARRANTY_EMAIL_CHECK_ENABLED).lower()
        )
        match_content = await self.get_setting(
            session,
            self.WARRANTY_EMAIL_CHECK_MATCH_CONTENT_KEY,
            self.DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_CONTENT
        )
        miss_content = await self.get_setting(
            session,
            self.WARRANTY_EMAIL_CHECK_MISS_CONTENT_KEY,
            self.DEFAULT_WARRANTY_EMAIL_CHECK_MISS_CONTENT
        )
        match_templates_raw = await self.get_setting(
            session,
            self.WARRANTY_EMAIL_CHECK_MATCH_TEMPLATES_KEY,
            ""
        )
        miss_templates_raw = await self.get_setting(
            session,
            self.WARRANTY_EMAIL_CHECK_MISS_TEMPLATES_KEY,
            ""
        )
        show_static_tutorial_raw = await self.get_setting(
            session,
            self.WARRANTY_EMAIL_CHECK_SHOW_STATIC_TUTORIAL_KEY,
            str(self.DEFAULT_WARRANTY_EMAIL_CHECK_SHOW_STATIC_TUTORIAL).lower()
        )

        sanitized_match_content = sanitize_rich_text(match_content)
        sanitized_miss_content = sanitize_rich_text(miss_content)
        safe_match_content = sanitized_match_content or self.DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_CONTENT
        safe_miss_content = sanitized_miss_content or self.DEFAULT_WARRANTY_EMAIL_CHECK_MISS_CONTENT
        match_templates = self._parse_warranty_email_check_templates(
            match_templates_raw,
            True,
            safe_match_content,
        )
        miss_templates = self._parse_warranty_email_check_templates(
            miss_templates_raw,
            False,
            safe_miss_content,
        )

        return {
            "enabled": self._parse_bool(
                enabled_raw,
                self.DEFAULT_WARRANTY_EMAIL_CHECK_ENABLED
            ),
            "show_static_tutorial": self._parse_bool(
                show_static_tutorial_raw,
                self.DEFAULT_WARRANTY_EMAIL_CHECK_SHOW_STATIC_TUTORIAL
            ),
            "match_content": match_templates[0]["content"],
            "miss_content": miss_templates[0]["content"],
            "match_templates": match_templates,
            "miss_templates": miss_templates,
        }

    def _normalize_sub2api_warranty_code_prefix(self, value: Optional[str]) -> str:
        raw_value = (value or self.DEFAULT_SUB2API_WARRANTY_CODE_PREFIX).strip().upper()
        normalized = "".join(ch for ch in raw_value if ch.isalnum() or ch == "-").strip("-")
        return (normalized or self.DEFAULT_SUB2API_WARRANTY_CODE_PREFIX)[:24]

    async def get_sub2api_warranty_redeem_config(self, session: AsyncSession) -> Dict[str, Any]:
        """获取质保名单判定命中后创建 Sub2API 订阅兑换码的配置。"""
        base_url = (await self.get_setting(session, self.SUB2API_WARRANTY_BASE_URL_KEY, "") or "").strip().rstrip("/")
        admin_api_key = (await self.get_setting(session, self.SUB2API_WARRANTY_ADMIN_API_KEY_KEY, "") or "").strip()
        group_id_raw = (await self.get_setting(session, self.SUB2API_WARRANTY_SUBSCRIPTION_GROUP_ID_KEY, "") or "").strip()
        code_prefix_raw = await self.get_setting(
            session,
            self.SUB2API_WARRANTY_CODE_PREFIX_KEY,
            self.DEFAULT_SUB2API_WARRANTY_CODE_PREFIX,
        )

        group_id: Optional[int] = None
        try:
            parsed_group_id = int(group_id_raw)
            if parsed_group_id > 0:
                group_id = parsed_group_id
        except (TypeError, ValueError):
            group_id = None

        return {
            "base_url": base_url,
            "admin_api_key": admin_api_key,
            "subscription_group_id": group_id,
            "code_prefix": self._normalize_sub2api_warranty_code_prefix(code_prefix_raw),
            "configured": bool(base_url and admin_api_key and group_id),
        }

    async def update_sub2api_warranty_redeem_config(
        self,
        session: AsyncSession,
        base_url: str = "",
        admin_api_key: str = "",
        subscription_group_id: Optional[int] = None,
        code_prefix: str = "",
    ) -> bool:
        """保存质保名单判定命中后创建 Sub2API 订阅兑换码的配置。"""
        group_id_value = ""
        if subscription_group_id is not None:
            try:
                group_id_int = int(subscription_group_id)
            except (TypeError, ValueError):
                raise ValueError("订阅分组 ID 必须为正整数")
            if group_id_int <= 0:
                raise ValueError("订阅分组 ID 必须为正整数")
            group_id_value = str(group_id_int)

        return await self.update_settings(
            session,
            {
                self.SUB2API_WARRANTY_BASE_URL_KEY: (base_url or "").strip().rstrip("/"),
                self.SUB2API_WARRANTY_ADMIN_API_KEY_KEY: (admin_api_key or "").strip(),
                self.SUB2API_WARRANTY_SUBSCRIPTION_GROUP_ID_KEY: group_id_value,
                self.SUB2API_WARRANTY_CODE_PREFIX_KEY: self._normalize_sub2api_warranty_code_prefix(code_prefix),
            }
        )

    async def update_warranty_email_check_config(
        self,
        session: AsyncSession,
        enabled: bool,
        show_static_tutorial: bool = False,
        match_content: str = "",
        miss_content: str = "",
        match_templates: Sequence[Dict[str, Any]] | None = None,
        miss_templates: Sequence[Dict[str, Any]] | None = None,
    ) -> bool:
        """
        更新前台质保邮箱名单判定模式配置。
        """

        raw_match_templates = (
            match_templates
            if match_templates
            else [
                self._build_warranty_email_check_template(
                    "match-default",
                    self.DEFAULT_WARRANTY_EMAIL_CHECK_MATCH_TEMPLATE_NAME,
                    match_content,
                )
            ]
        )
        raw_miss_templates = (
            miss_templates
            if miss_templates
            else [
                self._build_warranty_email_check_template(
                    "miss-default",
                    self.DEFAULT_WARRANTY_EMAIL_CHECK_MISS_TEMPLATE_NAME,
                    miss_content,
                )
            ]
        )
        sanitized_match_templates = self._normalize_warranty_email_check_templates(
            raw_match_templates,
            True,
        )
        sanitized_miss_templates = self._normalize_warranty_email_check_templates(
            raw_miss_templates,
            False,
        )
        sanitized_match_content = sanitized_match_templates[0]["content"]
        sanitized_miss_content = sanitized_miss_templates[0]["content"]

        return await self.update_settings(
            session,
            {
                self.WARRANTY_EMAIL_CHECK_ENABLED_KEY: str(bool(enabled)).lower(),
                self.WARRANTY_EMAIL_CHECK_SHOW_STATIC_TUTORIAL_KEY: str(bool(show_static_tutorial)).lower(),
                self.WARRANTY_EMAIL_CHECK_MATCH_CONTENT_KEY: sanitized_match_content,
                self.WARRANTY_EMAIL_CHECK_MISS_CONTENT_KEY: sanitized_miss_content,
                self.WARRANTY_EMAIL_CHECK_MATCH_TEMPLATES_KEY: json.dumps(
                    sanitized_match_templates,
                    ensure_ascii=False,
                ),
                self.WARRANTY_EMAIL_CHECK_MISS_TEMPLATES_KEY: json.dumps(
                    sanitized_miss_templates,
                    ensure_ascii=False,
                ),
            }
        )

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

    async def get_admin_sidebar_order(self, session: AsyncSession) -> list[str]:
        """
        获取管理后台侧边栏排序。存量配置缺失或损坏时回退到默认排序。
        """
        raw_order = await self.get_setting(session, self.ADMIN_SIDEBAR_ORDER_KEY, "")
        if not raw_order:
            return get_default_admin_sidebar_order()

        try:
            parsed_order = json.loads(raw_order)
            if isinstance(parsed_order, list):
                parsed_order = [item for item in parsed_order if item != "warranty_teams"]
            return normalize_admin_sidebar_order(parsed_order)
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            logger.warning("管理后台侧边栏排序配置无效，已使用默认排序: %s", e)
            return get_default_admin_sidebar_order()

    async def update_admin_sidebar_order(
        self,
        session: AsyncSession,
        order: Sequence[str]
    ) -> list[str]:
        """
        更新管理后台侧边栏排序。
        """
        normalized_order = normalize_admin_sidebar_order(order)
        success = await self.update_setting(
            session,
            self.ADMIN_SIDEBAR_ORDER_KEY,
            json.dumps(normalized_order, ensure_ascii=False)
        )
        if not success:
            raise RuntimeError("保存侧边栏排序失败")
        return normalized_order

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
