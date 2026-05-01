import unittest
from unittest.mock import AsyncMock, patch

from app.services.sub2api_warranty_client import Sub2APIWarrantyRedeemClient


class DummyResponse:
    status_code = 200

    def json(self):
        return {"data": {"redeem_code": {"code": "TMW-CODE"}}}


class Sub2APIWarrantyRedeemClientTests(unittest.IsolatedAsyncioTestCase):
    def test_build_code_is_deterministic_and_uses_prefix(self):
        client = Sub2APIWarrantyRedeemClient()

        first = client.build_code("Buyer@Example.com", 7, "tmw")
        second = client.build_code("buyer@example.com", 7, "TMW")

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("TMW-"))
        self.assertEqual(len(first), 24)

    async def test_create_subscription_code_posts_expected_payload(self):
        client = Sub2APIWarrantyRedeemClient()
        post = AsyncMock(return_value=DummyResponse())
        async_client = AsyncMock()
        async_client.__aenter__.return_value.post = post

        with patch("app.services.sub2api_warranty_client.httpx.AsyncClient", return_value=async_client):
            result = await client.create_subscription_code(
                base_url="https://sub2api.example.com/",
                admin_api_key="admin-key",
                code="TMW-CODE",
                group_id=12,
                validity_days=30,
                email="buyer@example.com",
                entry_id=7,
            )

        self.assertTrue(result["success"])
        post.assert_awaited_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://sub2api.example.com/api/v1/admin/redeem-codes")
        self.assertEqual(kwargs["headers"]["x-api-key"], "admin-key")
        self.assertTrue(kwargs["headers"]["Idempotency-Key"].startswith("team-manage-warranty-email-check-create-TMW-CODE-"))
        self.assertEqual(kwargs["json"]["type"], "subscription")
        self.assertEqual(kwargs["json"]["status"], "unused")
        self.assertEqual(kwargs["json"]["group_id"], 12)
        self.assertEqual(kwargs["json"]["validity_days"], 30)
        self.assertNotIn("user_id", kwargs["json"])

    def test_idempotency_key_changes_when_payload_changes(self):
        client = Sub2APIWarrantyRedeemClient()
        base_payload = {
            "code": "TMW-CODE",
            "type": "subscription",
            "value": 0,
            "status": "unused",
            "group_id": 12,
            "validity_days": 30,
            "notes": "team-manage warranty email-check: buyer@example.com",
        }
        changed_payload = {**base_payload, "validity_days": 29}

        self.assertNotEqual(
            client.build_idempotency_key("TMW-CODE", base_payload),
            client.build_idempotency_key("TMW-CODE", changed_payload),
        )



if __name__ == "__main__":
    unittest.main()
