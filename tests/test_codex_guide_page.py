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
        self.assertIn("目前 GPT Team 已全部失效", html)
        self.assertIn("纯血 Plus 号池", html)
        self.assertIn("https://api.sakms.top/register", html)
        self.assertIn("填写验证码后完成创建中转账户", html)
        self.assertIn("配置文件前必须完全关闭 Codex", html)
        self.assertIn("按邮箱质保剩余时间补发的中转兑换码", html)
        self.assertIn("质保补发的中转兑换码", html)
        self.assertIn("30刀订阅", html)
        self.assertIn("额度包兑换码必须选择 GPT-Plus", html)
        self.assertIn("不能选“质保补偿”，否则无法使用", html)
        self.assertIn("名称可按自己需要随便填写", html)
        self.assertIn("配置方式二：使用 cc-switch 一键配置", html)
        self.assertIn("https://github.com/farion1231/cc-switch/releases", html)
        self.assertIn("API 地址填写 <code>https://api.sakms.top/</code>", html)
        self.assertIn("/static/img/codex-guide/image-15.png", html)
        self.assertIn("GPT-Plus", html)
        self.assertIn("链动小铺", html)
        self.assertIn("/static/img/codex-guide/image-13.png", html)
        self.assertIn("/static/img/codex-guide/image-14.png", html)
        self.assertIn("codex-provider-sync/releases", html)
        self.assertIn("支持 gpt-5.5", html)
        self.assertIn("返回兑换页", html)
        self.assertIn('class="codex-key-flow"', html)
        self.assertIn('class="codex-key-step codex-key-step--focus"', html)
        self.assertIn("分组决定密钥使用的权益来源", html)

    def test_redeem_page_links_to_codex_guide(self):
        template = Path("app/templates/user/redeem.html").read_text(encoding="utf-8")

        self.assertIn('href="/codex-guide"', template)
        self.assertIn("Codex 教程", template)

    def test_sanitized_guide_assets_are_kept_under_static_directory(self):
        asset_dir = Path("app/static/img/codex-guide")

        for image_name in ("image-4.png", "image-5.png", "image-9.png", "image-12.png", "image-13.png", "image-14.png", "image-15.png"):
            self.assertTrue((asset_dir / image_name).exists())

        template = Path("app/templates/user/codex_guide.html").read_text(encoding="utf-8")

        self.assertIn("截图中的 API Key 已脱敏", template)
        self.assertIn("不要发给他人", template)


if __name__ == "__main__":
    unittest.main()
