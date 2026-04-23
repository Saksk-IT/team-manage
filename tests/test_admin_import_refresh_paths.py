from pathlib import Path
import unittest


class AdminImportRefreshPathsTests(unittest.TestCase):
    def test_import_refresh_helper_includes_codes_page(self):
        main_js = Path("app/static/js/main.js").read_text(encoding="utf-8")
        self.assertIn("normalizedPathname === '/admin/codes'", main_js)

    def test_single_team_refresh_uses_backend_message(self):
        template = Path("app/templates/admin/index.html").read_text(encoding="utf-8")
        self.assertIn("showToast(data.message || '刷新成功', 'success');", template)


if __name__ == "__main__":
    unittest.main()
