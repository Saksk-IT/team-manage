import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import BulkActionRequest, batch_enable_device_auth


class BatchEnableDeviceAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_failed_items_with_team_identity_and_error(self):
        mocked_results = [
            {
                "success": True,
                "team_id": 1,
                "email": "success@example.com",
                "message": "设备代码身份验证开启成功"
            },
            {
                "success": False,
                "team_id": 2,
                "email": "failed@example.com",
                "error": "Token 已过期且无法刷新"
            }
        ]

        with patch(
            "app.routes.admin.team_service.enable_device_code_auth",
            new=AsyncMock(side_effect=mocked_results)
        ):
            response = await batch_enable_device_auth(
                action_data=BulkActionRequest(ids=[1, 2]),
                db=object(),
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["success_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(
            payload["failed_items"],
            [
                {
                    "team_id": 2,
                    "email": "failed@example.com",
                    "error": "Token 已过期且无法刷新"
                }
            ]
        )


if __name__ == "__main__":
    unittest.main()
