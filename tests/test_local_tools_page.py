import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.routes.local_tools import (
    LocalToolFetchRequest,
    fetch_local_tool_page,
    local_record_workbench_page,
    local_tools_page,
)


class LocalToolsPageTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/local-tools", "headers": []})

    def _build_record_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/local-tools/records", "headers": []})

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

    async def test_local_record_workbench_renders_safe_local_import_page(self):
        response = await local_record_workbench_page(request=self._build_record_request())
        html = response.body.decode("utf-8")

        self.assertIn("本地记录工作台", html)
        self.assertIn("批量导入后形成记录", html)
        self.assertIn("数据仅保存在当前浏览器本地", html)
        self.assertIn("不会保存完整卡号、CVV 或短信 API Key", html)
        self.assertIn('id="recordBatchInput"', html)
        self.assertIn('id="importRecordWorkbenchBtn"', html)
        self.assertIn('id="recordItemsGrid"', html)
        self.assertIn("/static/js/local_records.js", html)
        self.assertIn("/static/css/local_records.css", html)
        self.assertNotIn("FULL_CARD_NUMBER", html)
        self.assertNotIn("CVV_VALUE", html)

    async def test_local_tool_fetch_page_rejects_non_http_url(self):
        with self.assertRaises(HTTPException) as context:
            await fetch_local_tool_page(LocalToolFetchRequest(url="javascript:alert(1)"))

        self.assertEqual(400, context.exception.status_code)

    async def test_local_tool_fetch_page_returns_remote_text_without_storage(self):
        class FakeResponse:
            status_code = 200
            content = b"yes|PayPal\xef\xbc\x9a024741\xe6\x98\xaf\xe6\x82\xa8\xe7\x9a\x84\xe9\xaa\x8c\xe8\xaf\x81\xe7\xa0\x81\xe3\x80\x82|(PayPal)|\xe5\x88\xb0\xe6\x9c\x9f\xe6\x97\xb6\xe9\x97\xb4\xef\xbc\x9a2026-06-29 00:00:00"
            encoding = "utf-8"
            headers = {"content-type": "text/plain; charset=utf-8"}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url):
                self.url = url
                return FakeResponse()

        with patch("app.routes.local_tools._is_blocked_fetch_host", return_value=False), patch(
            "app.routes.local_tools.httpx.AsyncClient",
            FakeAsyncClient,
        ):
            response = await fetch_local_tool_page(
                LocalToolFetchRequest(url="https://example.com/code")
            )

        self.assertTrue(response["success"])
        self.assertEqual(200, response["status_code"])
        self.assertIn("024741", response["text"])
        self.assertIn("text/plain", response["content_type"])


if __name__ == "__main__":
    unittest.main()
