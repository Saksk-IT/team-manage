import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    WarrantyEmailCheckSettingsRequest,
    update_warranty_email_check_settings,
)


class AdminWarrantyEmailCheckSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_warranty_email_check_settings_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_warranty_email_check_config",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_warranty_email_check_settings(
                warranty_data=WarrantyEmailCheckSettingsRequest(
                    enabled=True,
                    match_content="<p>在列表</p>",
                    miss_content="<p>不在列表</p>",
                ),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, "<p>在列表</p>", "<p>不在列表</p>")
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


if __name__ == "__main__":
    unittest.main()
