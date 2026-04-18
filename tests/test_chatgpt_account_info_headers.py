import unittest
from unittest.mock import AsyncMock

from app.services.chatgpt import ChatGPTService


class ChatGPTAccountInfoHeaderTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
