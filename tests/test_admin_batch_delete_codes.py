import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    BulkCodeActionRequest,
    batch_delete_codes,
)


class AdminBatchDeleteCodesTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_delete_codes_returns_success_counts(self):
        db = AsyncMock()

        async def delete_side_effect(code, session):
            if code == "CODE-OK-1":
                return {"success": True}
            if code == "CODE-OK-2":
                return {"success": True}
            return {"success": False, "error": "删除失败"}

        with patch(
            "app.routes.admin.redemption_service.delete_code",
            new=AsyncMock(side_effect=delete_side_effect)
        ) as mocked_delete:
            response = await batch_delete_codes(
                action_data=BulkCodeActionRequest(codes=["CODE-OK-1", "CODE-BAD-1", "CODE-OK-2"]),
                db=db,
                current_user={"username": "admin"}
            )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(mocked_delete.await_count, 3)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["success_count"], 2)
        self.assertEqual(payload["failed_count"], 1)


if __name__ == "__main__":
    unittest.main()
