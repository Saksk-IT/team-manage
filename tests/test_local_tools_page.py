import unittest

from starlette.requests import Request

from app.routes.local_tools import local_tools_page


class LocalToolsPageTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/local-tools", "headers": []})

    async def test_local_tools_page_renders_standalone_local_features(self):
        response = await local_tools_page(request=self._build_request())
        html = response.body.decode("utf-8")

        self.assertIn("本地快捷导入工具", html)
        self.assertIn("数据仅保存在当前浏览器本地", html)
        self.assertIn('id="batchContentInput"', html)
        self.assertIn('id="localToolsFileInput"', html)
        self.assertIn('id="importLocalToolsBtn"', html)
        self.assertIn('id="refreshAllSiteInfoBtn"', html)
        self.assertIn("点击完整标识即可复制", html)
        self.assertIn('class="workbench-layout"', html)
        self.assertIn('class="items-grid items-grid--workbench"', html)
        self.assertIn("/static/js/local_tools.js", html)
        self.assertIn("/static/css/local_tools.css", html)
        self.assertNotIn("管理员", html)


if __name__ == "__main__":
    unittest.main()
