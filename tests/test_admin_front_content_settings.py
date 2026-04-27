import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile
from starlette.datastructures import Headers
from starlette.requests import Request

from app.routes.admin import (
    CustomerServiceSettingsRequest,
    FrontAnnouncementSettingsRequest,
    PurchaseLinkSettingsRequest,
    front_page_settings_page,
    upload_customer_service_image,
    update_customer_service_settings,
    update_front_announcement_settings,
    update_purchase_link_settings,
)


class AdminFrontContentSettingsTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/front-page", "headers": []})

    async def test_front_page_settings_page_renders_front_forms(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.get_front_announcement_config",
            new=AsyncMock(return_value={"enabled": True, "content": "公告内容"})
        ), patch(
            "app.routes.admin.settings_service.get_customer_service_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "qr_code_url": "https://example.com/qrcode.png",
                "link_url": "https://example.com/contact",
                "link_text": "联系客服",
                "text_content": "微信：support001"
            })
        ), patch(
            "app.routes.admin.settings_service.get_purchase_link_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "url": "https://example.com/buy",
                "button_text": "购买套餐"
            })
        ):
            response = await front_page_settings_page(
                request=self._build_request(),
                db=db,
                current_user={"username": "admin", "is_super_admin": True}
            )

        html = response.body.decode("utf-8")

        self.assertIn("前台页面", html)
        self.assertIn('href="/admin/front-page"', html)
        self.assertIn("商品购买链接跳转", html)
        self.assertIn('id="purchaseLinkForm"', html)
        self.assertIn("前台公告通知", html)
        self.assertIn('id="frontAnnouncementForm"', html)
        self.assertIn("前台客服模块", html)
        self.assertIn('id="customerServiceForm"', html)

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

    async def test_update_customer_service_settings_accepts_uploaded_local_path(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.customer_service_upload_exists",
            return_value=True
        ), patch(
            "app.routes.admin.resolve_customer_service_upload_display_url",
            return_value="/uploads/customer-service/qrcode.png"
        ), patch(
            "app.routes.admin.settings_service.update_customer_service_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_customer_service_settings(
                customer_service_data=CustomerServiceSettingsRequest(
                    enabled=True,
                    qr_code_url="/uploads/customer-service/qrcode.png",
                    link_url="https://example.com/contact",
                    link_text="联系客服",
                    text_content=""
                ),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once()
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
        self.assertEqual(payload["error"], "客服二维码地址必须是有效的 http/https 链接或站内已上传且可访问的图片路径")

    async def test_update_purchase_link_settings_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_purchase_link_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_purchase_link_settings(
                purchase_link_data=PurchaseLinkSettingsRequest(
                    enabled=True,
                    url="https://example.com/buy",
                    button_text="购买套餐"
                ),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(
            db,
            True,
            "https://example.com/buy",
            "购买套餐"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_purchase_link_settings_rejects_invalid_url(self):
        db = AsyncMock()

        response = await update_purchase_link_settings(
            purchase_link_data=PurchaseLinkSettingsRequest(
                enabled=True,
                url="not-a-url",
                button_text="购买套餐"
            ),
            db=db,
            current_user={"username": "admin"}
        )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "商品购买链接必须是有效的 http/https 链接")

    async def test_update_purchase_link_settings_requires_url_when_enabled(self):
        db = AsyncMock()

        response = await update_purchase_link_settings(
            purchase_link_data=PurchaseLinkSettingsRequest(
                enabled=True,
                url="",
                button_text="购买套餐"
            ),
            db=db,
            current_user={"username": "admin"}
        )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "开启商品购买按钮时必须填写商品购买链接")

    async def test_upload_customer_service_image_returns_static_url(self):
        upload_file = UploadFile(
            file=io.BytesIO(b"fake-image"),
            filename="qrcode.png",
            headers=Headers({"content-type": "image/png"})
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.routes.admin.get_customer_service_upload_dir",
            return_value=Path(temp_dir)
        ):
            response = await upload_customer_service_image(
                image=upload_file,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["url"].startswith("/uploads/customer-service/"))

    async def test_upload_customer_service_image_rejects_invalid_content_type(self):
        upload_file = UploadFile(
            file=io.BytesIO(b"not-image"),
            filename="qrcode.txt",
            headers=Headers({"content-type": "text/plain"})
        )

        response = await upload_customer_service_image(
            image=upload_file,
            current_user={"username": "admin"}
        )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "仅支持 PNG、JPG、WEBP、GIF 格式图片")


if __name__ == "__main__":
    unittest.main()
