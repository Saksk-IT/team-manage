from pathlib import Path
import unittest

from starlette.requests import Request

from app.main import templates


class SubAdminImportModalTests(unittest.TestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/import-only", "headers": []})

    def test_base_template_hides_single_import_for_import_only_page(self):
        html = templates.env.get_template("base.html").render(
            request=self._build_request(),
            user={"username": "sub-admin", "is_super_admin": False},
            active_page="import_only"
        )

        self.assertNotIn("单个导入", html)
        self.assertNotIn('id="singleImport"', html)
        self.assertIn("批量导入", html)
        self.assertIn('id="batchImport" class="import-panel"', html)

    def test_import_modal_defaults_to_batch_import_on_import_only_page(self):
        main_js = Path("app/static/js/main.js").read_text(encoding="utf-8")
        self.assertIn("const initialTabId = isImportOnlyPage() ? 'batchImport' : 'singleImport';", main_js)


if __name__ == "__main__":
    unittest.main()
