import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.warranty import (
    WarrantyCheckRequest,
    WarrantyClaimRequest,
    WarrantyOrderStatusRequest,
    check_warranty,
    claim_warranty,
    refresh_warranty_order_status,
)


class WarrantyCheckRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_warranty_returns_order_list(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.warranty_service.get_warranty_claim_status",
            new=AsyncMock(return_value={
                "success": True,
                "can_claim": False,
                "latest_team": None,
                "warranty_info": {
                    "remaining_claims": 2,
                    "remaining_days": 3,
                    "remaining_seconds": 259199,
                    "remaining_time": "2天 23:59:59",
                    "expires_at": "2026-05-03T12:00:00",
                },
                "warranty_orders": [
                    {
                        "entry_id": 1,
                        "code": "CODE-123",
                        "display_code": "CODE-123",
                        "can_claim": False,
                        "can_refresh_status": True,
                        "latest_team": None,
                        "remaining_seconds": 259199,
                        "remaining_time": "2天 23:59:59",
                        "warranty_expires_at": "2026-05-03T12:00:00",
                    }
                ],
                "message": "已查询到 1 个质保订单，请对仍有剩余次数和天数的订单单独查询 Team 状态。"
            })
        ) as mocked_status:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                db_session=db
            )

        mocked_status.assert_awaited_once_with(db_session=db, email="buyer@example.com")
        self.assertTrue(result["success"])
        self.assertFalse(result["can_claim"])
        self.assertIsNone(result["latest_team"])
        self.assertEqual(result["warranty_orders"][0]["code"], "CODE-123")
        self.assertEqual(result["warranty_orders"][0]["remaining_time"], "2天 23:59:59")
        self.assertEqual(result["warranty_orders"][0]["warranty_expires_at"], "2026-05-03T12:00:00")
        self.assertTrue(result["warranty_orders"][0]["can_refresh_status"])

    async def test_refresh_warranty_order_status_route(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.warranty_service.refresh_warranty_order_status",
            new=AsyncMock(return_value={
                "success": True,
                "can_claim": True,
                "latest_team": {"id": 1, "status": "banned"},
                "warranty_order": {"entry_id": 2, "code": "CODE-123", "can_claim": True},
                "message": "该质保订单最近加入的 Team 已封禁，可以提交质保。",
                "error": None,
            })
        ) as mocked_refresh:
            result = await refresh_warranty_order_status(
                request=WarrantyOrderStatusRequest(
                    email="buyer@example.com",
                    code="CODE-123",
                    entry_id=2,
                ),
                db_session=db,
            )

        mocked_refresh.assert_awaited_once_with(
            db_session=db,
            email="buyer@example.com",
            entry_id=2,
            code="CODE-123",
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["can_claim"])

    async def test_check_warranty_rejects_invalid_status_result(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.warranty_service.get_warranty_claim_status",
            new=AsyncMock(return_value={"success": False, "error": "未找到该邮箱最近加入的 Team 记录"})
        ):
            with self.assertRaises(HTTPException) as ctx:
                await check_warranty(
                    request=WarrantyCheckRequest(email="buyer@example.com"),
                    db_session=db
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "未找到该邮箱最近加入的 Team 记录")

    async def test_claim_warranty_passes_selected_code_to_queue(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.invite_queue_service.submit_warranty_job",
            new=AsyncMock(return_value={"success": True, "job_id": 1})
        ) as mocked_submit:
            result = await claim_warranty(
                request=WarrantyClaimRequest(email="buyer@example.com", code="CODE-123"),
                db_session=db
            )

        mocked_submit.assert_awaited_once_with(
            db_session=db,
            email="buyer@example.com",
            code="CODE-123",
            entry_id=None,
        )
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
