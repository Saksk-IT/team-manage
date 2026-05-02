import unittest
from pathlib import Path

from starlette.requests import Request

from app.routes.user import codex_guide_page


class CodexGuidePageTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/codex-guide", "headers": []})

    async def test_codex_guide_page_renders_static_tutorial(self):
        response = await codex_guide_page(request=self._build_request())
        html = response.body.decode("utf-8")

        self.assertIn("Codex API 登录对接教程", html)
        self.assertIn("兑换中转 API Key，并接入 Codex", html)
        self.assertIn("https://api.sakms.top/register", html)
        self.assertIn("配置文件前必须完全关闭 Codex", html)
        self.assertIn("/static/img/codex-guide/image-12.png", html)
        self.assertIn("返回兑换页", html)

    def test_redeem_page_links_to_codex_guide(self):
        template = Path("app/templates/user/redeem.html").read_text(encoding="utf-8")

        self.assertIn('href="/codex-guide"', template)
        self.assertIn("Codex 教程", template)

    def test_sanitized_guide_assets_are_kept_under_static_directory(self):
        asset_dir = Path("app/static/img/codex-guide")

        for image_name in ("image-4.png", "image-5.png", "image-9.png", "image-12.png"):
            self.assertTrue((asset_dir / image_name).exists())

        template = Path("app/templates/user/codex_guide.html").read_text(encoding="utf-8")

        self.assertIn("截图中的 API Key 已脱敏", template)
        self.assertIn("不要发给他人", template)


if __name__ == "__main__":
    unittest.main()
