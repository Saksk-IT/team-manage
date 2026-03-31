import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    WarrantyServiceSettingsRequest,
    update_warranty_service_settings,
)


class AdminWarrantyServiceSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_warranty_service_settings_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_warranty_service_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_warranty_service_settings(
                warranty_data=WarrantyServiceSettingsRequest(enabled=True),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_warranty_service_settings_returns_500_on_failure(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_warranty_service_config",
            new=AsyncMock(return_value=False)
        ):
            response = await update_warranty_service_settings(
                warranty_data=WarrantyServiceSettingsRequest(enabled=False),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 500)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "保存失败")


if __name__ == "__main__":
    unittest.main()
