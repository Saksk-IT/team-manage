import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.routes.warranty import WarrantyCheckRequest, check_warranty


class WarrantyEmailCheckRouteTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self, query_string: bytes = b"") -> Request:
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/warranty/check",
            "query_string": query_string,
            "headers": [],
        })

    async def test_check_warranty_uses_email_check_mode_when_enabled(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "match_content": "<p><strong>已在列表</strong></p>",
                "miss_content": "<p>不在列表</p>",
                "match_templates": [
                    {"id": "match-a", "name": "命中 A", "content": "<p><strong>模板 A</strong></p>"},
                    {"id": "match-b", "name": "命中 B", "content": "<p>模板 B</p>"},
                ],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={"success": True, "matched": True, "matched_count": 1, "template_key": "match-a"})
        ) as mocked_membership, patch(
            "app.routes.warranty.warranty_service.get_warranty_claim_status",
            new=AsyncMock()
        ) as mocked_order_status, patch(
            "app.routes.warranty.warranty_service.ensure_warranty_email_check_redeem_code",
            new=AsyncMock(return_value={
                "success": True,
                "code": "TMW-AUTO",
                "remaining_days": 3,
                "reused": False,
            })
        ) as mocked_generate:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                http_request=self._build_request(),
                db_session=db,
            )

        mocked_membership.assert_awaited_once_with(
            db_session=db,
            email="buyer@example.com",
            match_templates=[
                {"id": "match-a", "name": "命中 A", "content": "<p><strong>模板 A</strong></p>"},
                {"id": "match-b", "name": "命中 B", "content": "<p>模板 B</p>"},
            ],
            miss_templates=[{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
        )
        mocked_order_status.assert_not_awaited()
        mocked_generate.assert_awaited_once_with(
            db_session=db,
            email="buyer@example.com",
            user_id=None,
            template_lock=None,
            warranty_entry=None,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "email_check")
        self.assertTrue(result["matched"])
        self.assertEqual(result["content_html"], "<p><strong>模板 A</strong></p>")
        self.assertEqual(result["content_render_mode"], "rich_text")
        self.assertEqual(result["message"], "模板 A")
        self.assertEqual(result["template_key"], "match-a")
        self.assertEqual(result["generated_redeem_code"], "TMW-AUTO")
        self.assertEqual(result["warranty_orders"], [])

    async def test_check_warranty_returns_miss_content_when_email_not_matched(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "match_content": "<p>已在列表</p>",
                "miss_content": "<p><em>不在列表</em></p>",
                "match_templates": [{"id": "match-a", "name": "命中 A", "content": "<p>已在列表</p>"}],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p><em>未命中模板</em></p>"}],
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={"success": True, "matched": False, "matched_count": 0, "template_key": "miss-a"})
        ):
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                http_request=self._build_request(),
                db_session=db,
            )

        self.assertFalse(result["matched"])
        self.assertEqual(result["content_html"], "<p><em>未命中模板</em></p>")
        self.assertEqual(result["message"], "未命中模板")
        self.assertEqual(result["template_key"], "miss-a")

    async def test_check_warranty_returns_static_tutorial_when_enabled(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "show_static_tutorial": True,
                "match_content": "<p>已在列表</p>",
                "miss_content": "<p>不在列表</p>",
                "match_templates": [{"id": "match-a", "name": "命中 A", "content": "<p>已在列表</p>"}],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={"success": True, "matched": True, "matched_count": 1, "template_key": "match-a"})
        ), patch(
            "app.routes.warranty.warranty_service.ensure_warranty_email_check_redeem_code",
            new=AsyncMock(return_value={
                "success": True,
                "code": "TMW-STATIC",
                "remaining_days": 7,
                "reused": False,
            })
        ):
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                http_request=self._build_request(),
                db_session=db,
            )

        self.assertEqual(result["mode"], "email_check")
        self.assertEqual(result["content_render_mode"], "static_tutorial")
        self.assertIn("warranty-static-tutorial", result["content_html"])
        self.assertIn("兑换中转 API Key，并接入 Codex", result["content_html"])
        self.assertIn("固定写死内容", result["content_html"])
        self.assertNotIn("/codex-guide", result["content_html"])
        self.assertEqual(result["message"], "邮箱已通过核查，已展示固定教程页面，请按下方步骤继续。")
        self.assertEqual(result["template_key"], "match-a")
        self.assertEqual(result["generated_redeem_code"], "TMW-STATIC")

    async def test_check_warranty_returns_static_tutorial_for_miss_when_enabled(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "show_static_tutorial": True,
                "match_content": "<p>已在列表</p>",
                "miss_content": "<p>不在列表</p>",
                "match_templates": [{"id": "match-a", "name": "命中 A", "content": "<p>已在列表</p>"}],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={"success": True, "matched": False, "matched_count": 0, "template_key": "miss-a"})
        ), patch(
            "app.routes.warranty.warranty_service.ensure_warranty_email_check_redeem_code",
            new=AsyncMock()
        ) as mocked_generate:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                http_request=self._build_request(),
                db_session=db,
            )

        mocked_generate.assert_not_awaited()
        self.assertEqual(result["content_render_mode"], "static_tutorial")
        self.assertIn("warranty-static-tutorial--miss", result["content_html"])
        self.assertIn("邮箱未命中名单", result["content_html"])
        self.assertNotIn("/codex-guide", result["content_html"])
        self.assertEqual(result["message"], "邮箱未命中名单，已展示固定教程页面，请按下方步骤继续。")
        self.assertIsNone(result["generated_redeem_code"])
        self.assertIsNone(result["generated_redeem_code_remaining_days"])


    async def test_check_warranty_generates_sub2api_code_when_user_id_present(self):
        db = AsyncMock()
        http_request = Request({
            "type": "http",
            "method": "POST",
            "path": "/warranty/check",
            "query_string": b"user_id=42",
            "headers": [],
        })

        template_lock = object()
        selected_entry = object()
        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "match_content": "<p>已在列表</p>",
                "miss_content": "<p>不在列表</p>",
                "match_templates": [{"id": "match-a", "name": "命中 A", "content": "<p>已在列表</p>"}],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={
                "success": True,
                "matched": True,
                "matched_count": 1,
                "template_key": "match-a",
                "template_lock": template_lock,
                "selected_entry": selected_entry,
            })
        ), patch(
            "app.routes.warranty.warranty_service.ensure_warranty_email_check_redeem_code",
            new=AsyncMock(return_value={
                "success": True,
                "code": "TMW-ABC",
                "remaining_days": 3,
                "reused": False,
            })
        ) as mocked_generate:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                http_request=http_request,
                db_session=db,
            )

        mocked_generate.assert_awaited_once_with(
            db_session=db,
            email="buyer@example.com",
            user_id=42,
            template_lock=template_lock,
            warranty_entry=selected_entry,
        )
        self.assertEqual(result["generated_redeem_code"], "TMW-ABC")
        self.assertEqual(result["generated_redeem_code_remaining_days"], 3)
        self.assertFalse(result["generated_redeem_code_reused"])


    async def test_check_warranty_generates_sub2api_code_without_user_id(self):
        db = AsyncMock()
        template_lock = object()
        selected_entry = object()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "match_content": "<p>已在列表</p>",
                "miss_content": "<p>不在列表</p>",
                "match_templates": [{"id": "match-a", "name": "命中 A", "content": "<p>已在列表</p>"}],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={
                "success": True,
                "matched": True,
                "matched_count": 1,
                "template_key": "match-a",
                "template_lock": template_lock,
                "selected_entry": selected_entry,
            })
        ), patch(
            "app.routes.warranty.warranty_service.ensure_warranty_email_check_redeem_code",
            new=AsyncMock(return_value={
                "success": True,
                "code": "TMW-NOUSER",
                "remaining_days": 30,
                "reused": False,
            })
        ) as mocked_generate:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                http_request=self._build_request(),
                db_session=db,
            )

        mocked_generate.assert_awaited_once_with(
            db_session=db,
            email="buyer@example.com",
            user_id=None,
            template_lock=template_lock,
            warranty_entry=selected_entry,
        )
        self.assertEqual(result["generated_redeem_code"], "TMW-NOUSER")
        self.assertEqual(result["generated_redeem_code_remaining_days"], 30)

    async def test_check_warranty_skips_sub2api_code_when_linked_team_is_usable(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "match_content": "<p>已在列表</p>",
                "miss_content": "<p>不在列表</p>",
                "match_templates": [{"id": "match-a", "name": "命中 A", "content": "<p>已在列表</p>"}],
                "miss_templates": [{"id": "miss-a", "name": "未命中 A", "content": "<p>不在列表</p>"}],
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={
                "success": True,
                "matched": True,
                "matched_count": 1,
                "template_key": "match-a",
                "skip_redeem_code_generation": True,
                "usable_linked_team": {"id": 7, "status": "full", "status_label": "已满"},
            })
        ), patch(
            "app.routes.warranty.warranty_service.ensure_warranty_email_check_redeem_code",
            new=AsyncMock()
        ) as mocked_generate:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                http_request=self._build_request(),
                db_session=db,
            )

        mocked_generate.assert_not_awaited()
        self.assertEqual(result["message"], "您所在的Team可以正常使用，无需提交质保")
        self.assertEqual(result["content_html"], "<p>您所在的Team可以正常使用，无需提交质保</p>")
        self.assertTrue(result["skip_redeem_code_generation"])
        self.assertEqual(result["usable_linked_team"]["status_label"], "已满")
        self.assertIsNone(result["generated_redeem_code"])
        self.assertIsNone(result["generated_redeem_code_remaining_days"])

    async def test_claim_warranty_rejects_when_email_check_mode_enabled(self):
        from fastapi import HTTPException
        from app.routes.warranty import WarrantyClaimRequest, claim_warranty

        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.invite_queue_service.submit_warranty_job",
            new=AsyncMock()
        ) as mocked_submit:
            with self.assertRaises(HTTPException) as ctx:
                await claim_warranty(
                    request=WarrantyClaimRequest(email="buyer@example.com"),
                    db_session=db,
                )

        mocked_submit.assert_not_awaited()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("邮箱名单判定模式", ctx.exception.detail)



if __name__ == "__main__":
    unittest.main()
