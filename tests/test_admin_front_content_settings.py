import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    CustomerServiceSettingsRequest,
    FrontAnnouncementSettingsRequest,
    update_customer_service_settings,
    update_front_announcement_settings,
)


class AdminFrontContentSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_front_announcement_settings_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_front_announcement_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_front_announcement_settings(
                announcement_data=FrontAnnouncementSettingsRequest(
                    enabled=True,
                    content="系统公告：维护通知"
                ),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, "系统公告：维护通知")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_customer_service_settings_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_customer_service_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_customer_service_settings(
                customer_service_data=CustomerServiceSettingsRequest(
                    enabled=True,
                    qr_code_url="https://example.com/qrcode.png",
                    link_url="https://example.com/contact",
                    link_text="联系客服",
                    text_content="微信：support001"
                ),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(
            db,
            True,
            "https://example.com/qrcode.png",
            "https://example.com/contact",
            "联系客服",
            "微信：support001"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_customer_service_settings_rejects_invalid_qr_url(self):
        db = AsyncMock()

        response = await update_customer_service_settings(
            customer_service_data=CustomerServiceSettingsRequest(
                enabled=True,
                qr_code_url="not-a-url",
                link_url="",
                link_text="",
                text_content=""
            ),
            db=db,
            current_user={"username": "admin"}
        )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "客服二维码地址必须是有效的 http/https 链接")


if __name__ == "__main__":
    unittest.main()
