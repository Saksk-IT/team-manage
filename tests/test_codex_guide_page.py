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
        self.assertIn("Image 2.0 生图", html)
        self.assertIn("Codex.app 是 GPT 官方推出的强大软件", html)
        self.assertIn("https://pay.ldxp.cn/shop/LSSZLMUY", html)
        self.assertIn("/static/img/codex-guide/image-16.png", html)
        self.assertIn("有任何问题请扫码加群", html)
        self.assertIn("https://api.sakms.top/register", html)
        self.assertIn("填写验证码后完成创建中转账户", html)
        self.assertIn("配置文件前必须完全关闭 Codex", html)
        self.assertIn("按邮箱质保剩余时间补发的中转兑换码", html)
        self.assertIn("质保补发的中转兑换码", html)
        self.assertIn("30刀订阅", html)
        self.assertIn("额度包兑换码必须选择 GPT-Plus", html)
        self.assertIn("不能选“质保补偿”，否则无法使用", html)
        self.assertIn("通过质保网站补发的中转兑换码", html)
        self.assertIn("选择“质保补偿”分组", html)
        self.assertIn("订阅模式", html)
        self.assertIn("每天 0 点后自动刷新", html)
        self.assertIn("额度模式", html)
        self.assertIn("使用时消耗网站账户里的额度", html)
        self.assertIn("创建密钥前请再次确认自己使用的是订阅还是额度", html)
        self.assertIn("名称可按自己需要随便填写", html)
        self.assertIn("下载好后先打开一次 Codex 初始化配置文件", html)
        self.assertIn("配置文件时一定要保持 Codex 进程关闭", html)
        self.assertIn("右键选择“记事本”打开", html)
        self.assertIn("配置方式二：使用 cc-switch 一键配置", html)
        self.assertIn("https://github.com/farion1231/cc-switch/releases", html)
        self.assertIn("API 地址填写 <code>https://api.sakms.top/</code>", html)
        self.assertIn("/static/img/codex-guide/image-15.png", html)
        self.assertIn("GPT-Plus", html)
        self.assertIn("链动小铺", html)
        self.assertIn("/static/img/codex-guide/image-13.png", html)
        self.assertIn("/static/img/codex-guide/image-14.png", html)
        self.assertIn("codex-provider-sync/releases", html)
        self.assertIn("429 Too Many Requests", html)
        self.assertIn("https://api.sakms.top/profile", html)
        self.assertIn("打开额度查询页面", html)
        self.assertIn("支持 gpt-5.5", html)
        self.assertIn("返回兑换页", html)
        self.assertIn('class="codex-key-flow"', html)
        self.assertIn('class="codex-key-step codex-key-step--focus"', html)
        self.assertIn("分组决定密钥使用的权益来源", html)

    def test_redeem_page_links_to_codex_guide(self):
        template = Path("app/templates/user/redeem.html").read_text(encoding="utf-8")
        redeem_js = Path("app/static/js/redeem.js").read_text(encoding="utf-8")

        self.assertIn('href="/codex-guide"', template)
        self.assertIn("Codex 教程", template)
        self.assertIn('href="/codex-guide"', redeem_js)
        self.assertIn("查看教程", redeem_js)
        self.assertIn("warranty-generated-code__guide", redeem_js)

    def test_sanitized_guide_assets_are_kept_under_static_directory(self):
        asset_dir = Path("app/static/img/codex-guide")

        for image_name in ("image-4.png", "image-5.png", "image-9.png", "image-12.png", "image-13.png", "image-14.png", "image-15.png", "image-16.png"):
            self.assertTrue((asset_dir / image_name).exists())

        template = Path("app/templates/user/codex_guide.html").read_text(encoding="utf-8")

        self.assertIn("截图中的 API Key 已脱敏", template)
        self.assertIn("不要发给他人", template)


if __name__ == "__main__":
    unittest.main()
