import unittest
import json
import shutil
import subprocess
from pathlib import Path
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
        self.assertIn("点击姓名、地址、卡号、有效期、附加字段等内容即可复制", html)
        self.assertIn("数据仅保存在当前浏览器本地", html)
        self.assertIn("完整卡号、电话、有效期与附加字段仅本地保存", html)
        self.assertIn("搜索姓名、地址、卡号、有效期、附加字段或电话", html)
        self.assertIn('id="recordBatchInput"', html)
        self.assertIn('id="importRecordWorkbenchBtn"', html)
        self.assertIn('id="recordItemsGrid"', html)
        self.assertIn("/static/js/local_records.js", html)
        self.assertIn("/static/css/local_records.css", html)
        self.assertNotIn("FULL_CARD_NUMBER", html)
        self.assertNotIn("CVV_VALUE", html)
        self.assertNotIn("点击按钮复制需要的字段", html)

    async def test_local_record_workbench_static_assets_use_clickable_values(self):
        static_root = Path(__file__).resolve().parents[1] / "app" / "static"
        script = (static_root / "js" / "local_records.js").read_text(encoding="utf-8")
        stylesheet = (static_root / "css" / "local_records.css").read_text(encoding="utf-8")

        self.assertIn("cardNumber", script)
        self.assertIn("cardExpiry", script)
        self.assertIn("formatCardExpiry", script)
        self.assertIn("createCopyField('卡号'", script)
        self.assertIn("createCopyField('有效期'", script)
        self.assertIn("createCopyField('附加字段'", script)
        self.assertIn("record-card__copy-value", script)
        self.assertIn("record-card__copy-value", stylesheet)
        self.assertNotIn("createRecordButton('复制姓名'", script)
        self.assertNotIn("复制卡尾号", script)
        self.assertNotIn("createCopyField('CVV'", script)

    def test_local_record_parser_normalizes_expiry_and_keeps_short_extra_code(self):
        if not shutil.which("node"):
            self.skipTest("node is required for local_records.js behavior check")

        static_root = Path(__file__).resolve().parents[1] / "app" / "static"
        script_path = static_root / "js" / "local_records.js"
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
function createElement(tag) {{
  return {{
    tag,
    style: {{}},
    className: '',
    classList: {{ add() {{}}, remove() {{}} }},
    dataset: {{}},
    children: [],
    hidden: false,
    value: '',
    textContent: '',
    innerHTML: '',
    setAttribute() {{}},
    addEventListener() {{}},
    append(...nodes) {{ this.children.push(...nodes); }},
    appendChild(node) {{ this.children.push(node); return node; }},
    removeChild() {{}},
    select() {{}},
  }};
}}
const elements = new Proxy({{}}, {{
  get(target, key) {{
    target[key] = target[key] || createElement(String(key));
    return target[key];
  }}
}});
const sandbox = {{
  console,
  Date,
  Object,
  String,
  Number,
  Array,
  JSON,
  RegExp,
  navigator: {{}},
  window: {{
    localStorage: {{
      getItem() {{ return null; }},
      setItem() {{}},
      removeItem() {{}},
    }},
  }},
  document: {{
    getElementById(id) {{ return elements[id]; }},
    createElement,
    body: createElement('body'),
    execCommand() {{ return true; }},
  }},
}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync({json.dumps(str(script_path))}, 'utf8'), sandbox);
const parsed = sandbox.parseRecordBatch(
  '4111111111111111----2029/3----987----+15550104567----https://example.com/api/get_sms?key=demo----Pat Example----456 Oak Ave, Seattle WA 98101, US'
);
const record = parsed.records[0];
function collectText(node) {{
  if (!node) return '';
  return [node.textContent || '', ...(node.children || []).map(collectText)].join('|');
}}
const renderedText = collectText(sandbox.renderRecordCard(record));
process.stdout.write(JSON.stringify({{
  cardExpiry: record.cardExpiry,
  extraCode: record.extraCode,
  warnings: record.warnings,
  renderedText,
  storedValues: [
    record.name,
    record.address,
    record.note,
    record.cardNumber,
    record.cardMasked,
    record.cardLast4,
    record.cardExpiry,
    record.extraCode,
    record.phone,
    record.phoneMasked,
    record.warnings.join(' '),
  ].join('|'),
}}));
"""
        completed = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual("03/29", payload["cardExpiry"])
        self.assertEqual("987", payload["extraCode"])
        self.assertIn("987", payload["storedValues"])
        self.assertIn("附加字段", payload["renderedText"])
        self.assertIn("987", payload["renderedText"])
        self.assertNotIn("CVV", " ".join(payload["warnings"]))
        self.assertNotIn("到期日", " ".join(payload["warnings"]))
        self.assertNotIn("https://example.com/api/get_sms", payload["storedValues"])
        self.assertNotIn("key=demo", payload["storedValues"])

    def test_local_record_parser_imports_delimiter_wrapped_plain_text(self):
        if not shutil.which("node"):
            self.skipTest("node is required for local_records.js behavior check")

        static_root = Path(__file__).resolve().parents[1] / "app" / "static"
        script_path = static_root / "js" / "local_records.js"
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
function createElement(tag) {{
  return {{
    tag,
    style: {{}},
    className: '',
    classList: {{ add() {{}}, remove() {{}} }},
    dataset: {{}},
    children: [],
    hidden: false,
    value: '',
    textContent: '',
    innerHTML: '',
    setAttribute() {{}},
    addEventListener() {{}},
    append(...nodes) {{ this.children.push(...nodes); }},
    appendChild(node) {{ this.children.push(node); return node; }},
    removeChild() {{}},
    select() {{}},
  }};
}}
const elements = new Proxy({{}}, {{
  get(target, key) {{
    target[key] = target[key] || createElement(String(key));
    return target[key];
  }}
}});
const sandbox = {{
  console,
  Date,
  Object,
  String,
  Number,
  Array,
  JSON,
  RegExp,
  navigator: {{}},
  window: {{
    localStorage: {{
      getItem() {{ return null; }},
      setItem() {{}},
      removeItem() {{}},
    }},
  }},
  document: {{
    getElementById(id) {{ return elements[id]; }},
    createElement,
    body: createElement('body'),
    execCommand() {{ return true; }},
  }},
}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync({json.dumps(str(script_path))}, 'utf8'), sandbox);
const parsed = sandbox.parseRecordBatch('Alex Demo----123 Test St\\n\\n----123----');
const record = parsed.records[1];
function collectText(node) {{
  if (!node) return '';
  return [node.textContent || '', ...(node.children || []).map(collectText)].join('|');
}}
const renderedText = collectText(sandbox.renderRecordCard(record));
process.stdout.write(JSON.stringify({{
  count: parsed.records.length,
  invalidCount: parsed.invalidLines.length,
  rawText: record && record.rawText,
  sequence: record && record.sequence,
  searchableText: record && sandbox.buildSearchableRecordText(record),
  renderedText,
}}));
"""
        completed = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(2, payload["count"])
        self.assertEqual(0, payload["invalidCount"])
        self.assertEqual(2, payload["sequence"])
        self.assertEqual("----123----", payload["rawText"])
        self.assertIn("----123----", payload["searchableText"])
        self.assertIn("纯文本", payload["renderedText"])
        self.assertIn("----123----", payload["renderedText"])

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
