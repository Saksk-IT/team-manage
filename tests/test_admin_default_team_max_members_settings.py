import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    DefaultTeamMaxMembersSettingsRequest,
    update_default_team_max_members_settings,
)


class AdminDefaultTeamMaxMembersSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_default_team_max_members_settings_returns_success(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_default_team_max_members",
            new=AsyncMock(return_value=True)
        ) as mocked_update:
            response = await update_default_team_max_members_settings(
                settings_data=DefaultTeamMaxMembersSettingsRequest(value=8),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_update.assert_awaited_once_with(db, 8)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_update_default_team_max_members_settings_returns_400_for_invalid_value(self):
        db = AsyncMock()

        with patch(
            "app.routes.admin.settings_service.update_default_team_max_members",
            new=AsyncMock(side_effect=ValueError("每个 Team 默认最大人数必须大于 0"))
        ):
            response = await update_default_team_max_members_settings(
                settings_data=DefaultTeamMaxMembersSettingsRequest(value=0),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertIn("每个 Team 默认最大人数必须大于 0", payload["error"])


if __name__ == "__main__":
    unittest.main()
