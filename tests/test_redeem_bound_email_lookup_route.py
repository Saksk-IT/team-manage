import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.redeem import (
    BoundEmailLookupRequest,
    BoundEmailWithdrawRequest,
    lookup_bound_email,
    withdraw_bound_email,
)


class RedeemBoundEmailLookupRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_bound_email_returns_full_email(self):
        db = AsyncMock()

        with patch(
            "app.routes.redeem.redemption_service.lookup_code_binding_email",
            new=AsyncMock(return_value={
                "success": True,
                "found": True,
                "bound": True,
                "used_by_email": "buyer@example.com",
                "status": "used",
                "used_at": "2026-04-23T10:00:00",
                "message": "已查询到该兑换码绑定邮箱",
                "error": None,
            })
        ) as mocked_lookup:
            result = await lookup_bound_email(
                request=BoundEmailLookupRequest(code="CODE-123"),
                db=db,
            )

        mocked_lookup.assert_awaited_once_with(code="CODE-123", db_session=db)
        self.assertTrue(result.success)
        self.assertTrue(result.found)
        self.assertTrue(result.bound)
        self.assertEqual(result.email, "buyer@example.com")
        self.assertEqual(result.code_status_label, "已使用")

    async def test_lookup_bound_email_returns_unbound_status(self):
        db = AsyncMock()

        with patch(
            "app.routes.redeem.redemption_service.lookup_code_binding_email",
            new=AsyncMock(return_value={
                "success": True,
                "found": True,
                "bound": False,
                "used_by_email": None,
                "status": "unused",
                "used_at": None,
                "message": "该兑换码当前未绑定邮箱",
                "error": None,
            })
        ):
            result = await lookup_bound_email(
                request=BoundEmailLookupRequest(code="UNUSED-001"),
                db=db,
            )

        self.assertTrue(result.success)
        self.assertTrue(result.found)
        self.assertFalse(result.bound)
        self.assertIsNone(result.email)
        self.assertEqual(result.code_status_label, "未使用")

    async def test_lookup_bound_email_raises_when_service_fails(self):
        db = AsyncMock()

        with patch(
            "app.routes.redeem.redemption_service.lookup_code_binding_email",
            new=AsyncMock(return_value={
                "success": False,
                "error": "数据库异常",
            })
        ):
            with self.assertRaises(HTTPException) as ctx:
                await lookup_bound_email(
                    request=BoundEmailLookupRequest(code="CODE-ERR"),
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.detail, "数据库异常")

    async def test_withdraw_bound_email_returns_success_message(self):
        db = AsyncMock()

        with patch(
            "app.routes.redeem.redemption_service.withdraw_record_by_code",
            new=AsyncMock(return_value={
                "success": True,
                "message": "成功撤回记录并恢复兑换码 CODE-123",
            })
        ) as mocked_withdraw:
            result = await withdraw_bound_email(
                request=BoundEmailWithdrawRequest(code="CODE-123"),
                db=db,
            )

        mocked_withdraw.assert_awaited_once_with(code="CODE-123", db_session=db)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "成功撤回记录并恢复兑换码 CODE-123")

    async def test_withdraw_bound_email_raises_when_service_fails(self):
        db = AsyncMock()

        with patch(
            "app.routes.redeem.redemption_service.withdraw_record_by_code",
            new=AsyncMock(return_value={
                "success": False,
                "error": "该兑换码当前未绑定邮箱，无需撤销",
            })
        ):
            with self.assertRaises(HTTPException) as ctx:
                await withdraw_bound_email(
                    request=BoundEmailWithdrawRequest(code="UNUSED-001"),
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "该兑换码当前未绑定邮箱，无需撤销")


if __name__ == "__main__":
    unittest.main()
