import json
import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.routes.admin import (
    MAX_WARRANTY_EMAIL_CHECK_RICH_TEXT_LENGTH,
    WarrantyEmailCheckSettingsRequest,
    update_warranty_email_check_settings,
    warranty_email_check_settings_page,
)


class AdminWarrantyEmailCheckSettingsTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/warranty-email-check", "headers": []})

    async def test_warranty_email_check_page_renders_sidebar_entry_and_rich_text_form(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "match_content": "<p><strong>在列表</strong></p>",
                "miss_content": "<p>不在列表</p>",
            })
        ), patch(
            "app.routes.admin.settings_service.get_number_pool_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.admin.settings_service.get_admin_sidebar_order",
            new=AsyncMock(return_value=None)
        ):
            response = await warranty_email_check_settings_page(
                request=self._build_request(),
                db=db,
                current_user={"username": "admin", "is_super_admin": True},
            )

        html = response.body.decode("utf-8")

        self.assertIn("质保名单判定", html)
        self.assertIn('href="/admin/warranty-email-check"', html)
        self.assertIn('id="warrantyEmailCheckForm"', html)
        self.assertIn('id="warrantyEmailCheckMatchContent"', html)
        self.assertIn('class="rich-text-editor"', html)
        self.assertIn('data-rich-text-command="bold"', html)
        self.assertIn('data-rich-text-command="createLink"', html)
        self.assertIn("<p><strong>在列表</strong></p>", html)
        self.assertIn("fetch('/admin/warranty-email-check'", html)
        self.assertIn("validationMessage", html)

    async def test_update_warranty_email_check_settings_accepts_long_rich_text(self):
        db = AsyncMock()
        long_content = "<p>" + ("长教程内容" * 2500) + "</p>"

        self.assertLess(len(long_content), MAX_WARRANTY_EMAIL_CHECK_RICH_TEXT_LENGTH)

        with patch(
            "app.routes.admin.settings_service.update_warranty_email_check_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_warranty_email_check_settings(
                warranty_data=WarrantyEmailCheckSettingsRequest(
                    enabled=True,
                    match_content=long_content,
                    miss_content="<p>未命中</p>",
                ),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, long_content, "<p>未命中</p>")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_warranty_email_check_settings_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_warranty_email_check_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_warranty_email_check_settings(
                warranty_data=WarrantyEmailCheckSettingsRequest(
                    enabled=True,
                    match_content="<p>在列表</p>",
                    miss_content="<p>不在列表</p>",
                ),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, "<p>在列表</p>", "<p>不在列表</p>")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_warranty_email_check_settings_returns_500_on_failure(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_warranty_email_check_config",
            new=AsyncMock(return_value=False)
        ):
            response = await update_warranty_email_check_settings(
                warranty_data=WarrantyEmailCheckSettingsRequest(
                    enabled=False,
                    match_content="",
                    miss_content="",
                ),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 500)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "保存失败")


if __name__ == "__main__":
    unittest.main()
