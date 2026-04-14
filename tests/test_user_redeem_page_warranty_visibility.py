import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.routes.user import redeem_page


class UserRedeemPageWarrantyVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    async def test_redeem_page_hides_warranty_content_when_disabled(self):
        request = self._build_request()
        db = AsyncMock()

        with patch(
            "app.services.settings.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.settings.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.team.TeamService.get_total_available_seats",
            new=AsyncMock(return_value=12)
        ):
            response = await redeem_page(request=request, db=db)

        html = response.body.decode("utf-8")

        self.assertIn("普通兑换", html)
        self.assertNotIn("质保服务", html)
        self.assertNotIn("质保说明", html)
        self.assertNotIn("提交质保", html)
        self.assertIn("warrantyServiceEnabled: false", html)
        self.assertIn("warrantyFakeSuccessEnabled: false", html)

    async def test_redeem_page_shows_warranty_content_when_enabled(self):
        request = self._build_request()
        db = AsyncMock()

        with patch(
            "app.services.settings.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.team.TeamService.get_total_available_seats",
            new=AsyncMock(return_value=12)
        ):
            response = await redeem_page(request=request, db=db)

        html = response.body.decode("utf-8")

        self.assertIn("质保服务", html)
        self.assertIn("质保说明", html)
        self.assertIn("如您购买了质保服务", html)
        self.assertIn("查看状态", html)
        self.assertNotIn("普通兑换码", html)
        self.assertNotIn("超级兑换码", html)
        self.assertIn("质保邮箱", html)
        self.assertIn("warrantyServiceEnabled: true", html)


if __name__ == "__main__":
    unittest.main()
