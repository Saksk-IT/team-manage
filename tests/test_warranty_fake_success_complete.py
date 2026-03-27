import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.warranty import complete_fake_warranty_success


class WarrantyFakeSuccessCompleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_fake_warranty_success_returns_remaining_spots(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.routes.warranty.settings_service.decrement_warranty_fake_success_remaining_spots",
            new=AsyncMock(return_value=88)
        ) as mocked_decrement:
            result = await complete_fake_warranty_success(db_session=db)

        mocked_decrement.assert_awaited_once_with(db)
        self.assertEqual(result, {"success": True, "remaining_spots": 88})

    async def test_complete_fake_warranty_success_rejects_when_disabled(self):
        db = AsyncMock()

        with patch(
            "app.routes.warranty.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": False})
        ):
            with self.assertRaises(HTTPException) as ctx:
                await complete_fake_warranty_success(db_session=db)

        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
