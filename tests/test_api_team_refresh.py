import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.api import refresh_team


class ApiTeamRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_team_commits_after_successful_sync(self):
        db = AsyncMock()

        with patch(
            "app.routes.api.team_service.sync_team_info",
            new=AsyncMock(return_value={"success": True, "message": "同步成功", "error": None})
        ) as mocked_sync:
            response = await refresh_team(
                team_id=1,
                force=False,
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_sync.assert_awaited_once_with(
            1,
            db,
            force_refresh=False,
            enforce_bound_email_cleanup=True,
        )
        db.commit.assert_awaited_once()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])

    async def test_refresh_team_commits_after_failed_sync(self):
        db = AsyncMock()

        with patch(
            "app.routes.api.team_service.sync_team_info",
            new=AsyncMock(return_value={"success": False, "message": None, "error": "Token 已过期"})
        ) as mocked_sync:
            response = await refresh_team(
                team_id=1,
                force=True,
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        mocked_sync.assert_awaited_once_with(
            1,
            db,
            force_refresh=True,
            enforce_bound_email_cleanup=True,
        )
        db.commit.assert_awaited_once()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], "Token 已过期")


if __name__ == "__main__":
    unittest.main()
