import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    AdminSidebarOrderSettingsRequest,
    update_admin_sidebar_order_settings,
)


class AdminSidebarOrderRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_admin_sidebar_order_settings_returns_saved_items(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_admin_sidebar_order",
            new=AsyncMock(return_value=["settings", "dashboard"])
        ) as mocked_update:
            response = await update_admin_sidebar_order_settings(
                sidebar_data=AdminSidebarOrderSettingsRequest(order=["settings", "dashboard"]),
                db=db,
                current_user={"username": "admin", "is_super_admin": True}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, ["settings", "dashboard"])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["order"][:2], ["settings", "dashboard"])
        self.assertEqual(payload["items"][0]["label"], "系统设置")

    async def test_update_admin_sidebar_order_settings_returns_400_for_invalid_order(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_admin_sidebar_order",
            new=AsyncMock(side_effect=ValueError("包含无效菜单项"))
        ):
            response = await update_admin_sidebar_order_settings(
                sidebar_data=AdminSidebarOrderSettingsRequest(order=["unknown"]),
                db=db,
                current_user={"username": "admin", "is_super_admin": True}
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertIn("包含无效菜单项", payload["error"])


if __name__ == "__main__":
    unittest.main()
