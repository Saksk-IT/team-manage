import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.warranty import WarrantyClaimRequest, claim_warranty


class WarrantyServiceToggleRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_warranty_rejects_when_warranty_service_disabled(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": False})
        ):
            with self.assertRaises(HTTPException) as ctx:
                await claim_warranty(
                    request=WarrantyClaimRequest(
                        ordinary_code="CODE-VALID",
                        email="buyer@example.com",
                        super_code="SUPER-CODE"
                    ),
                    db_session=db
                )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "前台质保服务未开启")


if __name__ == "__main__":
    unittest.main()
