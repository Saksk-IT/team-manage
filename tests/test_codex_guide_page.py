import unittest
from pathlib import Path

from starlette.requests import Request

from app.routes.user import (
    claude_code_guide_page,
    codex_guide_page,
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
        self.assertIn("cc-switch 极速配置", html)
        self.assertIn("Claude Code、Open Code、Open Claw 已拆为独立教程页", html)
        self.assertIn("目前 GPT Team 已全部失效", html)
        self.assertIn("纯血 Plus 号池", html)
        self.assertIn("Image 2.0 生图", html)
        self.assertIn("Codex.app 是 GPT 官方推出的强大软件", html)
        self.assertIn("https://pay.ldxp.cn/shop/LSSZLMUY", html)
        self.assertIn("/static/img/codex-guide/image-16.png", html)
        self.assertIn("有任何问题请扫码加群", html)
        self.assertIn("https://api.sakms.top/register", html)
        self.assertIn("填写验证码后完成创建中转账户", html)
        self.assertIn("填写邮箱、获取验证码、设置密码后完成注册", html)
        self.assertIn("配置文件前必须退出登录并完全关闭 Codex", html)
        self.assertIn("按邮箱质保剩余时间补发的中转兑换码", html)
        self.assertIn("质保补发的中转兑换码", html)
        self.assertIn("订阅类分组：质保补偿 / 订阅**", html)
        self.assertIn("额度兑换码：必须选择 GPT-Plus", html)
        self.assertIn("不能选“质保补偿”，否则无法使用", html)
        self.assertIn("质保补发码：选择质保补偿", html)
        self.assertIn("通过质保网站补发的中转兑换码", html)
        self.assertIn("选择“质保补偿”分组", html)
        self.assertIn("额度类分组：GPT", html)
        self.assertIn("分组选错会导致无法使用", html)
        self.assertIn("订阅模式", html)
        self.assertIn("每天 0 点后自动刷新", html)
        self.assertIn("额度模式", html)
        self.assertIn("使用时消耗网站账户里的额度", html)
        self.assertIn("创建密钥前请再次确认自己使用的是订阅还是额度", html)
        self.assertIn("名称可按自己需要随便填写", html)
        self.assertIn("下载好后必须先打开一次 Codex", html)
        self.assertIn("先打开 Codex 初始化配置文件", html)
        self.assertIn("配置文件时一定要保持 Codex 进程关闭", html)
        self.assertIn("请确保 Codex 进程没有在运行", html)
        self.assertIn("否则配置可能不会生效", html)
        self.assertIn("右键选择“记事本”打开", html)
        self.assertIn("简单方法极速配置：使用 cc-switch 一键配置", html)
        self.assertIn("https://github.com/farion1231/cc-switch/releases", html)
        self.assertIn("https://api.sakms.top/keys", html)
        self.assertIn("导入到 CCS", html)
        self.assertIn("出现 <strong>Sak AI</strong>，说明导入成功", html)
        self.assertIn("点击箭头指向的编辑按钮", html)
        self.assertIn("打开“完整 URL”按钮", html)
        self.assertIn("点击“启用”，系统会自动配置", html)
        self.assertIn("这里也可以直接查看账户余额", html)
        self.assertIn("完成 CC Switch 导入后，重新打开 Codex 即可直接使用", html)
        self.assertIn("如果需要输入 API 密钥", html)
        self.assertIn("从网站复制自己的 API Key 后直接粘贴进去", html)
        self.assertIn("注意：一定要重启 Codex", html)
        self.assertIn("/static/img/codex-guide/image-27.png", html)
        self.assertIn("/static/img/codex-guide/image-28.png", html)
        self.assertIn("/static/img/codex-guide/image-29.png", html)
        self.assertIn("/static/img/codex-guide/image-26.png", html)
        self.assertIn("/static/img/codex-guide/image-30.png", html)
        self.assertIn("GPT-Plus", html)
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
        self.assertIn("支持 gpt-5.5", html)
        self.assertIn("四个客户端教程互跳入口", html)
        self.assertIn("Codex 配置教程", html)
        self.assertIn('href="/claude-code-guide"', html)
        self.assertIn('href="/open-code-guide"', html)
        self.assertIn('href="/open-claw-guide"', html)
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
        self.assertLess(
            html.index("在自己的密钥操作区域点击“导入到 CCS”"),
            html.index("/static/img/codex-guide/image-27.png"),
        )
        self.assertLess(
            html.index("/static/img/codex-guide/image-27.png"),
            html.index("出现 <strong>Sak AI</strong>，说明导入成功"),
        )
        self.assertLess(
            html.index("点击箭头指向的编辑按钮"),
            html.index("/static/img/codex-guide/image-28.png"),
        )
        self.assertLess(
            html.index("/static/img/codex-guide/image-28.png"),
            html.index("打开“完整 URL”按钮"),
        )
        self.assertLess(
            html.index("打开“完整 URL”按钮"),
            html.index("/static/img/codex-guide/image-29.png"),
        )
        self.assertLess(
            html.index("/static/img/codex-guide/image-29.png"),
            html.index("点击“启用”，系统会自动配置"),
        )
        self.assertLess(
            html.index("注意：一定要重启 Codex"),
            html.index("/static/img/codex-guide/image-26.png"),
        )
        self.assertLess(
            html.index("/static/img/codex-guide/image-26.png"),
            html.index("如果需要输入 API 密钥"),
        )
        self.assertLess(
            html.index("如果需要输入 API 密钥"),
            html.index("/static/img/codex-guide/image-30.png"),
        )

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

        for image_name in ("image-5.png", "image-12.png", "image-14.png", "image-16.png", "image-17.png", "image-18.png", "image-19.png", "image-20.png", "image-22.png", "image-23.png", "image-26.png", "image-27.png", "image-28.png", "image-29.png", "image-30.png", "image-31.png"):
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
                    "cc-switch 一键导入 Claude Code",
                    "ANTHROPIC_BASE_URL",
                    "/static/img/codex-guide/image-22.png",
                    "/static/img/codex-guide/image-27.png",
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
        )

        for view_func, path, expected_values in cases:
            with self.subTest(path=path):
                response = await view_func(request=Request({"type": "http", "method": "GET", "path": path, "headers": []}))
                html = response.body.decode("utf-8")

                self.assertIn('href="/codex-guide"', html)
                self.assertIn('href="/claude-code-guide"', html)
                self.assertIn('href="/open-code-guide"', html)
                self.assertIn('href="/open-claw-guide"', html)
                self.assertIn("四个客户端教程互跳入口", html)
                self.assertIn('aria-current="page"', html)
                self.assertIn("先创建 Key", html)
                for expected in expected_values:
                    self.assertIn(expected, html)

    def test_static_guide_default_width_is_wider(self):
        css = Path("app/static/css/codex-guide.css").read_text(encoding="utf-8")

        self.assertIn("width: min(100%, 1180px);", css)
        self.assertIn("width: min(100%, 1280px);", css)
        self.assertIn(".codex-client-guide-grid", css)
        self.assertIn(".codex-client-guide-grid--all", css)
        self.assertIn(".codex-client-guide-card--active", css)


if __name__ == "__main__":
    unittest.main()
