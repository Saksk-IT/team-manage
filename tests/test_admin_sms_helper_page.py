import unittest
from unittest.mock import patch

from starlette.requests import Request

from app.routes.admin_sms_helper import open_sms_helper_target, sms_helper_page


class AdminSmsHelperPageTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self, path: str) -> Request:
        return Request({"type": "http", "method": "GET", "path": path, "headers": []})

    async def test_sms_helper_page_renders_phone_and_open_entry(self):
        with patch("app.routes.admin_sms_helper.settings.sms_helper_phone", "+15722257869"), patch(
            "app.routes.admin_sms_helper.settings.sms_helper_url",
            "https://example.com/api/get_sms?key=test-key"
        ):
            response = await sms_helper_page(
                request=self._build_request("/admin/sms-helper"),
                current_user={"username": "admin", "is_admin": True},
            )

        html = response.body.decode("utf-8")
        self.assertIn("短信快捷工具", html)
        self.assertIn("+15722257869", html)
        self.assertIn('id="copySmsHelperPhoneBtn"', html)
        self.assertIn('href="/admin/sms-helper/open"', html)
        self.assertIn("已配置快捷打开地址", html)

    async def test_sms_helper_open_route_redirects_to_configured_url(self):
        with patch("app.routes.admin_sms_helper.settings.sms_helper_url", "https://example.com/api/get_sms?key=test-key"):
            response = await open_sms_helper_target(
                current_user={"username": "admin", "is_admin": True},
            )

        self.assertEqual(307, response.status_code)
        self.assertEqual("https://example.com/api/get_sms?key=test-key", response.headers["location"])

    async def test_sms_helper_page_ignores_invalid_config_values(self):
        with patch("app.routes.admin_sms_helper.settings.sms_helper_phone", "<script>alert(1)</script>"), patch(
            "app.routes.admin_sms_helper.settings.sms_helper_url",
            "javascript:alert(1)"
        ):
            response = await sms_helper_page(
                request=self._build_request("/admin/sms-helper"),
                current_user={"username": "admin", "is_admin": True},
            )

        html = response.body.decode("utf-8")
        self.assertIn("未配置", html)
        self.assertNotIn('href="/admin/sms-helper/open"', html)


if __name__ == "__main__":
    unittest.main()
