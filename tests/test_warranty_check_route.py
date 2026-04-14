import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.warranty import WarrantyCheckRequest, check_warranty


class WarrantyCheckRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_warranty_returns_latest_team_status(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.warranty_service.get_warranty_claim_status",
            new=AsyncMock(return_value={
                "success": True,
                "can_claim": True,
                "latest_team": {
                    "id": 1,
                    "team_name": "Banned Team",
                    "email": "owner@example.com",
                    "account_id": "acc-1",
                    "status": "banned",
                    "status_label": "封禁",
                    "redeemed_at": "2026-04-15T00:00:00",
                    "expires_at": None,
                    "code": "CODE-123",
                    "is_warranty_redemption": False,
                },
                "warranty_info": {"remaining_claims": 2, "remaining_days": 3},
                "message": "该邮箱最近加入的 Team 已封禁，可以继续提交质保。"
            })
        ) as mocked_status:
            result = await check_warranty(
                request=WarrantyCheckRequest(email="buyer@example.com"),
                db_session=db
            )

        mocked_status.assert_awaited_once_with(db_session=db, email="buyer@example.com")
        self.assertTrue(result["success"])
        self.assertTrue(result["can_claim"])
        self.assertEqual(result["latest_team"]["status"], "banned")

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


if __name__ == "__main__":
    unittest.main()
