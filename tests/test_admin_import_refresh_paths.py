from pathlib import Path
import unittest


class AdminImportRefreshPathsTests(unittest.TestCase):
    def test_import_refresh_helper_includes_codes_page(self):
        main_js = Path("app/static/js/main.js").read_text(encoding="utf-8")
        self.assertIn("normalizedPathname === '/admin/codes'", main_js)


if __name__ == "__main__":
    unittest.main()
