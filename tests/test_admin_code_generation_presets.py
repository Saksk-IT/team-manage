from pathlib import Path
import unittest

from starlette.requests import Request

from app.main import templates


class AdminCodeGenerationPresetTests(unittest.TestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/codes", "headers": []})

    def test_generate_code_modal_renders_preset_controls(self):
        html = templates.env.get_template("base.html").render(
            request=self._build_request(),
            user={"username": "admin", "is_super_admin": True},
            active_page="codes",
            stats={
                "available_seats": 5,
                "unused": 0,
                "remaining_code_capacity": 5,
            },
        )

        self.assertIn('data-code-preset-scope="single"', html)
        self.assertIn('data-code-preset-scope="batch"', html)
        self.assertIn('name="presetName"', html)
        self.assertIn("保存当前为预设", html)
        self.assertIn("有效期、质保天数和质保次数", html)
        self.assertIn("默认 10 次质保次数", html)
        self.assertIn('/static/js/code_generation_presets.js', html)

    def test_preset_js_contains_builtin_and_custom_preset_handlers(self):
        preset_js = Path("app/static/js/code_generation_presets.js").read_text(encoding="utf-8")

        self.assertIn("DEFAULT_CODE_GENERATION_PRESETS", preset_js)
        self.assertIn("7天体验", preset_js)
        self.assertIn("30天标准", preset_js)
        self.assertIn("90天长期", preset_js)
        self.assertIn("永久兑换", preset_js)
        self.assertIn("saveCodeGenerationPreset", preset_js)
        self.assertIn("applyCodeGenerationPreset", preset_js)
        self.assertIn("team_manage_code_generation_presets_v1", preset_js)


if __name__ == "__main__":
    unittest.main()
