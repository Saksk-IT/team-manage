import unittest
from unittest.mock import AsyncMock

from app.services.chatgpt import ChatGPTService


class ChatGPTAccountInfoHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_error_details_supports_detail_object_code(self):
        service = ChatGPTService()

        error_data = {"detail": {"code": "deactivated_workspace"}}

        self.assertEqual(service._extract_error_code(error_data), "deactivated_workspace")
        self.assertEqual(
            service._extract_error_message(error_data, fallback_error="fallback"),
            "deactivated_workspace",
        )

    async def test_get_account_info_includes_account_header_when_account_id_is_provided(self):
        service = ChatGPTService()
        service._make_request = AsyncMock(return_value={
            "success": True,
            "data": {"accounts": {}},
            "error": None,
        })

        await service.get_account_info(
            "access-token",
            db_session=object(),
            identifier="owner@example.com",
            account_id="fd06a12b-6da8-446a-9608-db17401443df",
        )

        service._make_request.assert_awaited_once()
        args, kwargs = service._make_request.await_args
        self.assertEqual(args[0], "GET")
        self.assertIn("Authorization", args[2])
        self.assertEqual(
            args[2].get("chatgpt-account-id"),
            "fd06a12b-6da8-446a-9608-db17401443df",
        )
        self.assertEqual(kwargs["identifier"], "owner@example.com")

    async def test_get_account_info_preserves_error_code_from_request_failure(self):
        service = ChatGPTService()
        service._make_request = AsyncMock(return_value={
            "success": False,
            "error": "workspace 已停用",
            "error_code": "deactivated_workspace",
        })

        result = await service.get_account_info(
            "access-token",
            db_session=object(),
            identifier="owner@example.com",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "workspace 已停用")
        self.assertEqual(result["error_code"], "deactivated_workspace")

    async def test_get_members_preserves_error_code_from_request_failure(self):
        service = ChatGPTService()
        service._make_request = AsyncMock(return_value={
            "success": False,
            "error": "workspace 已停用",
            "error_code": "deactivated_workspace",
        })

        result = await service.get_members(
            "access-token",
            "acc-123",
            db_session=object(),
            identifier="owner@example.com",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "workspace 已停用")
        self.assertEqual(result["error_code"], "deactivated_workspace")

    async def test_get_invites_preserves_error_code_from_request_failure(self):
        service = ChatGPTService()
        service._make_request = AsyncMock(return_value={
            "success": False,
            "error": "workspace 已停用",
            "error_code": "deactivated_workspace",
        })

        result = await service.get_invites(
            "access-token",
            "acc-123",
            db_session=object(),
            identifier="owner@example.com",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "workspace 已停用")
        self.assertEqual(result["error_code"], "deactivated_workspace")


if __name__ == "__main__":
    unittest.main()
