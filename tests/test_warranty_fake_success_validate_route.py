import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.warranty import WarrantyClaimRequest, validate_fake_warranty_success


class WarrantyFakeSuccessValidateRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_fake_warranty_success_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.warranty_service.validate_warranty_claim_input",
            new=AsyncMock(return_value={"success": True})
        ) as mocked_validate:
            result = await validate_fake_warranty_success(
                request=WarrantyClaimRequest(
                    ordinary_code="CODE-VALID",
                    email="buyer@example.com",
                    super_code="SUPER-CODE"
                ),
                db_session=db
            )

        mocked_validate.assert_awaited_once()
        self.assertEqual(result, {"success": True, "message": "校验通过"})

    async def test_validate_fake_warranty_success_rejects_when_disabled(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": False})
        ):
            with self.assertRaises(HTTPException) as ctx:
                await validate_fake_warranty_success(
                    request=WarrantyClaimRequest(
                        ordinary_code="CODE-VALID",
                        email="buyer@example.com",
                        super_code="SUPER-CODE"
                    ),
                    db_session=db
                )

        self.assertEqual(ctx.exception.status_code, 400)

    async def test_validate_fake_warranty_success_rejects_invalid_payload(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.warranty_service.validate_warranty_claim_input",
            new=AsyncMock(return_value={"success": False, "error": "邮箱与普通兑换码不匹配"})
        ):
            with self.assertRaises(HTTPException) as ctx:
                await validate_fake_warranty_success(
                    request=WarrantyClaimRequest(
                        ordinary_code="CODE-VALID",
                        email="buyer@example.com",
                        super_code="SUPER-CODE"
                    ),
                    db_session=db
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "邮箱与普通兑换码不匹配")


if __name__ == "__main__":
    unittest.main()
