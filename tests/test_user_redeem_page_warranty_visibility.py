import unittest
from pathlib import Path
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
            "app.services.settings.settings_service.get_front_announcement_config",
            new=AsyncMock(return_value={"enabled": False, "content": ""})
        ), patch(
            "app.services.settings.settings_service.get_customer_service_config",
            new=AsyncMock(return_value={
                "enabled": False,
                "qr_code_url": "",
                "link_url": "",
                "link_text": "",
                "text_content": ""
            })
        ), patch(
            "app.services.settings.settings_service.get_purchase_link_config",
            new=AsyncMock(return_value={
                "enabled": False,
                "url": "",
                "button_text": ""
            })
        ), patch(
            "app.services.settings.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.settings.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.settings.settings_service.get_number_pool_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.team.TeamService.get_total_available_seats",
            new=AsyncMock(return_value=12)
        ):
            response = await redeem_page(request=request, db=db)

        html = response.body.decode("utf-8")

        self.assertIn("兑换服务", html)
        self.assertIn("查询绑定邮箱", html)
        self.assertNotIn("自助撤销", html)
        self.assertIn('id="boundEmailLookupForm"', html)
        self.assertIn("可查询当前绑定的完整邮箱。撤销请联系客服处理。", html)
        self.assertNotIn("质保服务", html)
        self.assertNotIn("质保说明", html)
        self.assertNotIn("提交质保", html)
        self.assertNotIn("公告通知", html)
        self.assertNotIn("客服支持", html)
        self.assertNotIn('id="customerServiceFab"', html)
        self.assertNotIn('id="purchaseLinkButton"', html)
        self.assertIn("warrantyServiceEnabled: false", html)
        self.assertIn("warrantyFakeSuccessEnabled: false", html)

    async def test_redeem_page_shows_warranty_content_when_enabled(self):
        request = self._build_request()
        db = AsyncMock()

        with patch(
            "app.services.settings.settings_service.get_front_announcement_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "content": "系统公告：今晚 10 点维护"
            })
        ), patch(
            "app.services.settings.settings_service.get_customer_service_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "qr_code_url": "https://example.com/qrcode.png",
                "link_url": "https://example.com/contact",
                "link_text": "联系客服",
                "text_content": "微信：support001"
            })
        ), patch(
            "app.services.settings.settings_service.get_purchase_link_config",
            new=AsyncMock(return_value={
                "enabled": True,
                "url": "https://example.com/buy",
                "button_text": "购买套餐"
            })
        ), patch(
            "app.services.settings.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.settings.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.settings.settings_service.get_number_pool_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.team.TeamService.get_total_available_seats",
            new=AsyncMock(return_value=12)
        ):
            response = await redeem_page(request=request, db=db)

        html = response.body.decode("utf-8")

        self.assertIn("质保服务", html)
        self.assertIn("查询绑定邮箱", html)
        self.assertNotIn("自助撤销", html)
        self.assertIn('id="boundEmailLookupForm"', html)
        self.assertIn("可查询当前绑定的完整邮箱。撤销请联系客服处理。", html)
        self.assertIn("质保说明", html)
        self.assertIn("如您购买了质保服务", html)
        self.assertIn("查询订单", html)
        self.assertIn("公告通知", html)
        self.assertIn("系统公告：今晚 10 点维护", html)
        announcement_index = html.index('id="frontAnnouncement"')
        lookup_index = html.index('id="lookupCardTitle"')
        sidebar_index = html.index('<aside class="front-sidebar"')
        self.assertLess(announcement_index, lookup_index)
        self.assertLess(announcement_index, sidebar_index)
        self.assertIn("front-announcement-card", html)
        self.assertIn('id="purchaseLinkButton"', html)
        self.assertIn('href="https://example.com/buy"', html)
        self.assertIn("购买套餐", html)
        self.assertIn("客服支持", html)
        self.assertIn('id="customerServiceFab"', html)
        self.assertIn('id="customerServicePanel"', html)
        self.assertIn('id="customerServiceGroupReminder"', html)
        self.assertIn('id="customerServicePromptModal"', html)
        self.assertIn('id="customerServicePromptConfirmBtn"', html)
        self.assertIn("建议扫码加群", html)
        self.assertNotIn("support-column", html)
        self.assertIn("扫描二维码联系客服", html)
        self.assertIn("链接跳转联系客服", html)
        self.assertIn("文字客服信息", html)
        self.assertIn("微信：support001", html)
        self.assertNotIn("普通兑换码", html)
        self.assertNotIn("超级兑换码", html)
        self.assertIn("质保邮箱", html)
        self.assertIn("warrantyServiceEnabled: true", html)
        self.assertIn("warrantyEmailCheckEnabled: false", html)

    async def test_redeem_page_switches_warranty_copy_for_email_check_mode(self):
        request = self._build_request()
        db = AsyncMock()

        with patch(
            "app.services.settings.settings_service.get_front_announcement_config",
            new=AsyncMock(return_value={"enabled": False, "content": ""})
        ), patch(
            "app.services.settings.settings_service.get_customer_service_config",
            new=AsyncMock(return_value={
                "enabled": False,
                "qr_code_url": "",
                "link_url": "",
                "link_text": "",
                "text_content": ""
            })
        ), patch(
            "app.services.settings.settings_service.get_purchase_link_config",
            new=AsyncMock(return_value={
                "enabled": False,
                "url": "",
                "button_text": ""
            })
        ), patch(
            "app.services.settings.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_number_pool_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.team.TeamService.get_total_available_seats",
            new=AsyncMock(return_value=12)
        ):
            response = await redeem_page(request=request, db=db)

        html = response.body.decode("utf-8")

        self.assertIn("输入邮箱查询质保资格", html)
        self.assertIn("查询质保资格", html)
        self.assertIn("系统仅判断该邮箱是否在质保邮箱列表内", html)
        self.assertIn("warrantyEmailCheckEnabled: true", html)
        self.assertIn("warrantyFakeSuccessEnabled: false", html)

    def test_redeem_js_does_not_expose_front_withdraw_action(self):
        js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "redeem.js"
        js = js_path.read_text(encoding="utf-8")

        self.assertNotIn("/redeem/bound-email/withdraw", js)
        self.assertNotIn("boundEmailWithdrawBtn", js)
        self.assertNotIn("撤销绑定并恢复兑换码", js)


if __name__ == "__main__":
    unittest.main()
