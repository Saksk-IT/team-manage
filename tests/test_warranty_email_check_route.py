import unittest
from unittest.mock import AsyncMock, patch

from app.routes.warranty import WarrantyCheckRequest, check_warranty


class WarrantyEmailCheckRouteTests(unittest.IsolatedAsyncioTestCase):
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
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={"success": True, "matched": True, "matched_count": 1})
        ) as mocked_membership, patch(
            "app.routes.warranty.warranty_service.get_warranty_claim_status",
            new=AsyncMock()
        ) as mocked_order_status:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                db_session=db,
            )

        mocked_membership.assert_awaited_once_with(db_session=db, email="buyer@example.com")
        mocked_order_status.assert_not_awaited()
        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "email_check")
        self.assertTrue(result["matched"])
        self.assertEqual(result["content_html"], "<p><strong>已在列表</strong></p>")
        self.assertEqual(result["message"], "已在列表")
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
            })
        ), patch(
            "app.routes.warranty.warranty_service.check_warranty_email_membership",
            new=AsyncMock(return_value={"success": True, "matched": False, "matched_count": 0})
        ):
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                db_session=db,
            )

        self.assertFalse(result["matched"])
        self.assertEqual(result["content_html"], "<p><em>不在列表</em></p>")
        self.assertEqual(result["message"], "不在列表")

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
