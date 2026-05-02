import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import UploadFile
from starlette.datastructures import Headers
from starlette.requests import Request

from app.routes.admin import (
    MAX_WARRANTY_EMAIL_CHECK_RICH_TEXT_LENGTH,
    WarrantyEmailCheckSettingsRequest,
    code_generation_records_page,
    upload_warranty_email_check_image,
    update_warranty_email_check_settings,
    warranty_email_check_settings_page,
)


class AdminWarrantyEmailCheckSettingsTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self, path: str = "/admin/warranty-email-check") -> Request:
        return Request({"type": "http", "method": "GET", "path": path, "headers": []})

    async def test_warranty_email_check_page_renders_sidebar_entry_and_rich_text_form(self):
        db = AsyncMock()
        with patch(
            "app.routes.admin.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "show_static_tutorial": False,
                "match_content": "<p><strong>在列表</strong></p>",
                "miss_content": "<p>不在列表</p>",
                "match_templates": [
                    {"id": "match-a", "name": "命中 A", "content": "<p><strong>在列表</strong></p>"},
                    {"id": "match-b", "name": "命中 B", "content": "<p>命中 B</p>"},
                ],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
            })
        ), patch(
            "app.routes.admin.settings_service.get_number_pool_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.admin.settings_service.get_admin_sidebar_order",
            new=AsyncMock(return_value=None)
        ), patch(
            "app.routes.admin.settings_service.get_sub2api_warranty_redeem_config",
            new=AsyncMock(return_value={
                "base_url": "https://sub2api.example.com",
                "admin_api_key": "admin-key",
                "subscription_group_id": 12,
                "code_prefix": "TMW",
                "configured": True,
            })
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
        self.assertIn('id="warrantyEmailCheckShowStaticTutorial"', html)
        self.assertIn('name="show_static_tutorial"', html)
        self.assertIn('id="warrantyEmailCheckMatchTemplates"', html)
        self.assertIn('data-add-template="match"', html)
        self.assertIn('data-add-template="miss"', html)
        self.assertIn('class="rich-text-editor"', html)
        self.assertIn('data-rich-text-command="bold"', html)
        self.assertIn('data-rich-text-command="createLink"', html)
        self.assertIn('data-rich-text-command="insertImage"', html)
        self.assertIn("uploadWarrantyRichTextImage", html)
        self.assertIn("normalizeTemplateList", html)
        self.assertIn("match_templates", html)
        self.assertIn("/admin/warranty-email-check/upload-image", html)
        self.assertIn('\\u003cp\\u003e\\u003cstrong\\u003e', html)
        self.assertIn('\\u547d\\u4e2d B', html)
        self.assertIn("fetch('/admin/warranty-email-check'", html)
        self.assertIn("validationMessage", html)
        self.assertIn('id="sub2apiWarrantyBaseUrl"', html)
        self.assertIn("https://sub2api.example.com", html)
        self.assertIn('href="/admin/code-generation-records"', html)
        self.assertNotIn("最近生成记录", html)
        self.assertNotIn("TMW-GENERATED", html)
        db.execute.assert_not_called()

    async def test_code_generation_records_page_renders_generated_codes(self):
        db = AsyncMock()
        lock = SimpleNamespace(
            email="buyer@example.com",
            generated_redeem_code="TMW-GENERATED",
            generated_redeem_code_remaining_days=30,
            generated_redeem_code_entry_id=7,
            generated_redeem_code_generated_at=None,
        )
        entry = SimpleNamespace(id=7, expires_at=None, remaining_claims=1)
        records_result = MagicMock()
        records_result.all.return_value = [(lock, entry)]
        stats_result = MagicMock()
        stats_result.one.return_value = (1, 1, 30)
        today_result = MagicMock()
        today_result.scalar.return_value = 0
        db.execute.side_effect = [records_result, stats_result, today_result]

        with patch(
            "app.routes.admin.settings_service.get_number_pool_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.admin.settings_service.get_admin_sidebar_order",
            new=AsyncMock(return_value=None)
        ):
            response = await code_generation_records_page(
                request=self._build_request("/admin/code-generation-records"),
                db=db,
                current_user={"username": "admin", "is_super_admin": True},
            )

        html = response.body.decode("utf-8")

        self.assertIn("兑换码生成记录", html)
        self.assertIn('href="/admin/code-generation-records"', html)
        self.assertIn('menu-item active', html)
        self.assertIn("TMW-GENERATED", html)
        self.assertIn("buyer@example.com", html)
        self.assertIn("最近生成记录", html)
        self.assertIn("生成总数", html)
        self.assertIn("涉及邮箱", html)

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
                    show_static_tutorial=True,
                    match_content=long_content,
                    miss_content="<p>未命中</p>",
                ),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, True, long_content, "<p>未命中</p>", [], [])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_warranty_email_check_settings_returns_success(self):
        db = AsyncMock()

        match_templates = [{"id": "match-a", "name": "命中 A", "content": "<p>在列表</p>"}]
        miss_templates = [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}]

        with patch(
            "app.routes.admin.settings_service.update_warranty_email_check_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_warranty_email_check_settings(
                warranty_data=WarrantyEmailCheckSettingsRequest(
                    enabled=True,
                    show_static_tutorial=False,
                    match_content="<p>在列表</p>",
                    miss_content="<p>不在列表</p>",
                    match_templates=match_templates,
                    miss_templates=miss_templates,
                ),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, False, "<p>在列表</p>", "<p>不在列表</p>", match_templates, miss_templates)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])


    async def test_update_warranty_email_check_settings_saves_sub2api_config_when_provided(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_warranty_email_check_config",
            new=AsyncMock(return_value=True),
        ) as mocked_update, patch(
            "app.routes.admin.settings_service.update_sub2api_warranty_redeem_config",
            new=AsyncMock(return_value=True),
        ) as mocked_sub2api_update:
            response = await update_warranty_email_check_settings(
                warranty_data=WarrantyEmailCheckSettingsRequest(
                    enabled=True,
                    show_static_tutorial=False,
                    match_content="<p>在列表</p>",
                    miss_content="<p>不在列表</p>",
                    sub2api_base_url="https://sub2api.example.com/",
                    sub2api_admin_api_key="admin-key",
                    sub2api_subscription_group_id=12,
                    sub2api_code_prefix="tmw",
                ),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, False, "<p>在列表</p>", "<p>不在列表</p>", [], [])
        mocked_sub2api_update.assert_awaited_once_with(
            db,
            base_url="https://sub2api.example.com",
            admin_api_key="admin-key",
            subscription_group_id=12,
            code_prefix="tmw",
        )
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
                    show_static_tutorial=False,
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

    async def test_upload_warranty_email_check_image_returns_upload_url(self):
        upload_file = UploadFile(
            file=io.BytesIO(b"\x89PNG\r\n\x1a\nfake-image"),
            filename="pasted.png",
            headers=Headers({"content-type": "image/png"})
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.routes.admin.get_warranty_rich_text_upload_dir",
            return_value=Path(temp_dir)
        ):
            response = await upload_warranty_email_check_image(
                image=upload_file,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["url"].startswith("/uploads/warranty-email-check/"))

    async def test_upload_warranty_email_check_image_rejects_invalid_type(self):
        upload_file = UploadFile(
            file=io.BytesIO(b"not-image"),
            filename="pasted.txt",
            headers=Headers({"content-type": "text/plain"})
        )

        response = await upload_warranty_email_check_image(
            image=upload_file,
            current_user={"username": "admin"},
        )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "仅支持 PNG、JPG、WEBP、GIF 格式图片")

    async def test_upload_warranty_email_check_image_rejects_mismatched_content(self):
        upload_file = UploadFile(
            file=io.BytesIO(b"not-a-real-png"),
            filename="pasted.png",
            headers=Headers({"content-type": "image/png"})
        )

        response = await upload_warranty_email_check_image(
            image=upload_file,
            current_user={"username": "admin"},
        )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "图片内容与格式不匹配")


if __name__ == "__main__":
    unittest.main()
