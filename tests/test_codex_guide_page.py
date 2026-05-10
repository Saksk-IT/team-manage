import unittest
from pathlib import Path

from starlette.requests import Request

from app.routes.user import (
    claude_code_guide_page,
    codex_guide_page,
    mobile_guide_page,
    open_claw_guide_page,
    open_code_guide_page,
)


class CodexGuidePageTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/codex-guide", "headers": []})

    async def test_codex_guide_page_renders_static_tutorial(self):
        response = await codex_guide_page(request=self._build_request())
        html = response.body.decode("utf-8")

        self.assertIn("Codex API 登录对接教程", html)
        self.assertIn("兑换中转 API Key，并接入 Codex", html)
        self.assertIn("手动接入 Codex", html)
        self.assertIn("Claude Code、Open Code、Open Claw 请打开对应独立教程页", html)
        self.assertIn("移动端请查看 Chatbox 教程", html)
        self.assertIn("Codex App 是 GPT 官方推出的强大软件", html)
        self.assertNotIn("目前 GPT Team 已全部失效", html)
        self.assertNotIn("纯血 Plus 号池", html)
        self.assertIn("https://pay.ldxp.cn/shop/LSSZLMUY", html)
        self.assertIn("/static/img/codex-guide/image-16.png", html)
        self.assertIn("有任何问题请扫码加群", html)
        self.assertIn("https://api.sakms.top/register", html)
        self.assertIn("https://api.sakms.top/redeem", html)
        self.assertIn("填写验证码后完成创建中转账户", html)
        self.assertIn("填写邮箱、获取验证码、设置密码后完成注册", html)
        self.assertIn("配置文件前必须退出登录并完全关闭 Codex", html)
        self.assertIn("按邮箱质保剩余时间补发的中转兑换码", html)
        self.assertIn("质保补发的中转兑换码", html)
        self.assertIn("订阅类分组：质保补偿 / 订阅**", html)
        self.assertIn("链动小铺额度包：必须选择 GPT 分组", html)
        self.assertIn("链动小铺订阅包：选择对应订阅分组", html)
        self.assertIn("质保补发码：选择质保补偿", html)
        self.assertIn("通过质保网站补发的中转兑换码", html)
        self.assertIn("选择“质保补偿”分组", html)
        self.assertIn("额度类分组：GPT", html)
        self.assertIn("订阅类购买：对应订阅分组", html)
        self.assertIn("分组选错会导致无法使用", html)
        self.assertIn("订阅模式", html)
        self.assertIn("每天 0 点后自动刷新", html)
        self.assertIn("额度模式", html)
        self.assertIn("使用时消耗网站账户里的额度", html)
        self.assertIn("创建密钥前请再次确认自己使用的是订阅还是额度", html)
        self.assertIn("名称可按自己需要随便填写", html)
        self.assertIn("下载好后必须先打开一次 Codex", html)
        self.assertIn("先打开 Codex 初始化配置文件", html)
        self.assertIn("请确保 Codex 进程没有在运行", html)
        self.assertIn("否则配置可能不会生效", html)
        self.assertIn("在 C 盘找到用户文件夹", html)
        self.assertIn("显示隐藏文件", html)
        self.assertIn("Command", html)
        self.assertIn("Shift", html)
        self.assertIn("https://api.sakms.top/keys", html)
        self.assertIn("3.1 手动配置 Codex 系列", html)
        self.assertIn("按第二章“使用密钥”弹窗中的 Codex CLI 接入配置", html)
        self.assertNotIn("GPT-Plus", html)
        self.assertIn("链动小铺", html)
        self.assertIn("/static/img/codex-guide/image-19.png", html)
        self.assertIn("/static/img/codex-guide/image-14.png", html)
        self.assertIn("/static/img/codex-guide/image-17.png", html)
        self.assertIn("/static/img/codex-guide/image-18.png", html)
        self.assertIn("/static/img/codex-guide/image-20.png", html)
        self.assertIn("链动小铺额度兑换码选“GPT”或订阅分组", html)
        self.assertIn("/static/img/codex-guide/image-31.png", html)
        self.assertIn("codex-provider-sync/releases", html)
        self.assertIn("429 Too Many Requests", html)
        self.assertIn("https://api.sakms.top/profile", html)
        self.assertIn("打开额度查询页面", html)
        self.assertIn("客户端教程互跳入口", html)
        self.assertIn("Codex 配置教程", html)
        self.assertIn('href="/claude-code-guide"', html)
        self.assertIn('href="/open-code-guide"', html)
        self.assertIn('href="/open-claw-guide"', html)
        self.assertIn('href="/mobile-guide"', html)
        self.assertIn('aria-current="page"', html)
        self.assertNotIn('id="configureClaudeCode"', html)
        self.assertNotIn('id="configureOpenCode"', html)
        self.assertNotIn('id="configureOpenClaw"', html)
        self.assertIn("返回兑换页", html)
        self.assertIn('class="codex-key-flow"', html)
        self.assertIn('class="codex-key-step codex-key-step--focus"', html)
        self.assertIn('class="codex-group-grid"', html)
        self.assertIn('class="codex-alert codex-alert--important codex-alert--standout"', html)
        self.assertIn("分组决定密钥使用的权益来源", html)
        self.assertNotIn("cc-switch", html)
        self.assertNotIn("CC Switch", html)
        self.assertNotIn("导入到 CCS", html)
        self.assertNotIn("Sak AI", html)
        self.assertNotIn("完整 URL", html)

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

        for image_name in (
            "image-5.png",
            "image-12.png",
            "image-14.png",
            "image-16.png",
            "image-17.png",
            "image-18.png",
            "image-19.png",
            "image-20.png",
            "image-22.png",
            "image-23.png",
            "image-26.png",
            "image-27.png",
            "image-28.png",
            "image-29.png",
            "image-30.png",
            "image-31.png",
            "image-32.png",
            "image-33.png",
            "image-34.png",
            "image-35.png",
            "image-36.png",
            "image-37.png",
            "image-38.png",
            "image-39.png",
            "image-40.png",
            "image-41.png",
            "image-42.png",
            "image-43.png",
            "image-44.png",
            "image-45.png",
            "image-46.png",
        ):
            self.assertTrue((asset_dir / image_name).exists())

        template = Path("app/templates/user/codex_guide.html").read_text(encoding="utf-8")

        self.assertIn("截图中的 API Key 已脱敏", template)
        self.assertIn("不要发给他人", template)

    async def test_split_client_guide_pages_render(self):
        cases = (
            (
                claude_code_guide_page,
                "/claude-code-guide",
                (
                    "Claude Code 配置教程",
                    "从第一步开始：注册、兑换、创建 Key",
                    "通过 <code>settings.json</code> 或系统环境变量手动接入 Claude Code",
                    "ANTHROPIC_BASE_URL",
                    "/static/img/codex-guide/image-22.png",
                ),
            ),
            (
                open_code_guide_page,
                "/open-code-guide",
                (
                    "Open Code 配置教程",
                    "从第一步开始：注册、兑换、创建 Key",
                    "安装并首次启动 Open Code",
                    "opencode.json",
                    "https://opencode.ai/docs/config",
                ),
            ),
            (
                open_claw_guide_page,
                "/open-claw-guide",
                (
                    "Open Claw 配置教程",
                    "从第一步开始：注册、兑换、创建 Key",
                    "models.providers",
                    "openai-responses",
                    "腾讯云在线配置",
                ),
            ),
            (
                mobile_guide_page,
                "/mobile-guide",
                (
                    "移动端配置教程",
                    "Chatbox",
                    "OpenAI response API 兼容",
                    "https://chatboxai.app/zh",
                    "/static/img/codex-guide/image-32.png",
                ),
            ),
        )

        for view_func, path, expected_values in cases:
            with self.subTest(path=path):
                response = await view_func(request=Request({"type": "http", "method": "GET", "path": path, "headers": []}))
                html = response.body.decode("utf-8")

                self.assertIn('href="/codex-guide"', html)
                self.assertIn('href="/claude-code-guide"', html)
                self.assertIn('href="/open-code-guide"', html)
                self.assertIn('href="/open-claw-guide"', html)
                self.assertIn('href="/mobile-guide"', html)
                self.assertIn("客户端教程互跳入口", html)
                self.assertIn('aria-current="page"', html)
                self.assertIn("先创建 Key", html)
                for expected in expected_values:
                    self.assertIn(expected, html)
                if path in ("/codex-guide", "/claude-code-guide"):
                    self.assertNotIn("cc-switch", html)
                    self.assertNotIn("导入到 CCS", html)
                    self.assertNotIn("Sak AI", html)

    def test_static_guide_default_width_is_wider(self):
        css = Path("app/static/css/codex-guide.css").read_text(encoding="utf-8")

        self.assertIn("width: min(100%, 1180px);", css)
        self.assertIn("width: min(100%, 1280px);", css)
        self.assertIn(".codex-client-guide-grid", css)
        self.assertIn(".codex-client-guide-grid--all", css)
        self.assertIn(".codex-client-guide-card--active", css)
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", css)


if __name__ == "__main__":
    unittest.main()
