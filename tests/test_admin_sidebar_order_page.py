import unittest
import os
import tempfile
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.routes.admin import settings_page
from app.services.settings import settings_service


class AdminSidebarOrderPageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        settings_service.clear_cache()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        settings_service.clear_cache()
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})

    async def test_settings_page_renders_sidebar_order_form(self):
        async with self.Session() as db:
            with patch(
                "app.routes.admin.settings_service.get_proxy_config",
                new=AsyncMock(return_value={"enabled": False, "proxy": ""})
            ), patch(
                "app.routes.admin.settings_service.get_log_level",
                new=AsyncMock(return_value="INFO")
            ), patch(
                "app.routes.admin.settings_service.get_team_auto_refresh_config",
                new=AsyncMock(return_value={"enabled": True, "interval_minutes": 5})
            ), patch(
                "app.routes.admin.settings_service.get_warranty_expiry_auto_cleanup_config",
                new=AsyncMock(return_value={"enabled": False})
            ), patch(
                "app.routes.admin.settings_service.get_default_team_max_members",
                new=AsyncMock(return_value=5)
            ), patch(
                "app.routes.admin.settings_service.get_redeem_service_config",
                new=AsyncMock(return_value={"enabled": True})
            ), patch(
                "app.routes.admin.settings_service.get_warranty_service_config",
                new=AsyncMock(return_value={"enabled": True})
            ), patch(
                "app.routes.admin.settings_service.get_warranty_fake_success_config",
                new=AsyncMock(return_value={"enabled": False})
            ), patch(
                "app.routes.admin.settings_service.get_number_pool_config",
                new=AsyncMock(return_value={"enabled": False})
            ), patch(
                "app.routes.admin.settings_service.get_setting",
                new=AsyncMock(side_effect=["", "10", ""])
            ), patch(
                "app.routes.admin.settings_service.get_admin_sidebar_order",
                new=AsyncMock(return_value=["settings", "dashboard"])
            ):
                response = await settings_page(
                    request=self._build_request(),
                    db=db,
                    current_user={"username": "admin", "is_super_admin": True}
                )

        html = response.body.decode("utf-8")

        self.assertIn('id="sidebarOrderForm"', html)
        self.assertIn('data-menu-id="settings"', html)
        self.assertIn("后台侧边栏排序", html)
        self.assertNotIn('id="warrantyEmailCheckForm"', html)
        self.assertIn('data-menu-id="warranty_email_check"', html)
        self.assertIn('href="/admin/warranty-email-check"', html)
        self.assertIn('data-menu-id="code_generation_records"', html)
        self.assertIn('href="/admin/code-generation-records"', html)
        self.assertLess(html.index('data-menu-id="settings"'), html.index('data-menu-id="dashboard"'))


if __name__ == "__main__":
    unittest.main()
