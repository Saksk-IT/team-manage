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
        self.assertIn('id="batchImportTag"', html)
        self.assertIn('data-import-tag="other_paid"', html)
        self.assertIn('data-import-tag="self_paid"', html)

    def test_import_modal_defaults_to_batch_import_on_import_only_page(self):
        main_js = Path("app/static/js/main.js").read_text(encoding="utf-8")
        self.assertIn("const initialTabId = isImportOnlyPage() ? 'batchImport' : 'singleImport';", main_js)
        self.assertIn("导入后直接进入统一控制台 Team 池", main_js)
        self.assertNotIn("导入后进入待分类池", main_js)
        self.assertNotIn("等待总管理员审核", main_js)

    def test_review_page_template_exposes_batch_classify_actions(self):
        template = Path("app/templates/admin/index.html").read_text(encoding="utf-8")

        self.assertIn("批量进入控制台", template)
        self.assertNotIn("批量进入质保 Team", template)
        self.assertIn("data-import-status", template)
        self.assertIn('name="review_status"', template)
        self.assertIn('name="import_tag"', template)
        self.assertIn('name="imported_from"', template)
        self.assertIn('name="imported_to"', template)
        self.assertIn("/admin/teams/batch-classify/stream", template)
        self.assertIn("requireSelectedPendingReviewTargets", template)
        self.assertNotIn("setWarrantyDaysQuickValue(this, 30)", template)


if __name__ == "__main__":
    unittest.main()
