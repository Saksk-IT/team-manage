import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    TeamAutoRefreshSettingsRequest,
    WarrantyExpiryAutoCleanupSettingsRequest,
    update_team_auto_refresh_settings,
    update_warranty_expiry_auto_cleanup_settings,
)


class AdminTeamAutoRefreshSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_team_auto_refresh_settings_returns_success(self):
        db = AsyncMock()

        with (
            patch(
                "app.routes.admin.settings_service.update_team_auto_refresh_config",
                new=AsyncMock(return_value=True)
            ) as mocked_update,
            patch("app.routes.admin.team_auto_refresh_service.wake") as mocked_wake,
        ):
            response = await update_team_auto_refresh_settings(
                refresh_data=TeamAutoRefreshSettingsRequest(enabled=True, interval_minutes=15),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True, 15)
        mocked_wake.assert_called_once_with()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_team_auto_refresh_settings_returns_400_for_invalid_interval(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_team_auto_refresh_config",
            new=AsyncMock(side_effect=ValueError("自动刷新间隔必须在 1 到 1440 分钟之间"))
        ):
            response = await update_team_auto_refresh_settings(
                refresh_data=TeamAutoRefreshSettingsRequest(enabled=True, interval_minutes=0),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertIn("自动刷新间隔必须在 1 到 1440 分钟之间", payload["error"])


class AdminWarrantyExpiryAutoCleanupSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_warranty_expiry_auto_cleanup_settings_returns_success(self):
        db = AsyncMock()

        with (
            patch(
                "app.routes.admin.settings_service.update_warranty_expiry_auto_cleanup_config",
                new=AsyncMock(return_value=True),
            ) as mocked_update,
            patch("app.routes.admin.warranty_expiry_cleanup_service.wake") as mocked_wake,
        ):
            response = await update_warranty_expiry_auto_cleanup_settings(
                cleanup_data=WarrantyExpiryAutoCleanupSettingsRequest(enabled=True),
                db=db,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, True)
        mocked_wake.assert_called_once_with()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])


if __name__ == "__main__":
    unittest.main()
