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

    def _run_local_records_node(self, node_body: str) -> dict:
        if not shutil.which("node"):
            self.skipTest("node is required for local_records.js behavior check")

        static_root = Path(__file__).resolve().parents[1] / "app" / "static"
        script_path = static_root / "js" / "local_records.js"
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
const noop = () => {{}};
function createElement(tag) {{
  return {{ tag, style: {{}}, className: '', dataset: {{}}, children: [], hidden: false, checked: false,
    value: '', textContent: '', innerHTML: '', classList: {{ add: noop, remove: noop }},
    setAttribute: noop, addEventListener: noop, removeChild: noop, select: noop,
    append(...nodes) {{ this.children.push(...nodes); }},
    appendChild(node) {{ this.children.push(node); return node; }},
  }};
}}
const elements = new Proxy({{}}, {{
  get(target, key) {{ target[key] = target[key] || createElement(String(key)); return target[key]; }}
}});
const sandbox = {{
  console, Date, Object, String, Number, Array, JSON, RegExp, URL, navigator: {{}},
  window: {{
    localStorage: {{ getItem() {{ return null; }}, setItem: noop, removeItem: noop }},
  }},
  document: {{
    getElementById(id) {{ return elements[id]; }},
    createElement, body: createElement('body'),
    execCommand() {{ return true; }},
  }},
}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync({json.dumps(str(script_path))}, 'utf8'), sandbox);
{node_body}
"""
        completed = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def _run_local_tools_node(self, node_body: str) -> dict:
        if not shutil.which("node"):
            self.skipTest("node is required for local_tools.js behavior check")

        static_root = Path(__file__).resolve().parents[1] / "app" / "static"
        script_path = static_root / "js" / "local_tools.js"
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
const noop = () => {{}};
function createElement(tag) {{
  return {{ tag, style: {{}}, className: '', dataset: {{}}, children: [], hidden: false,
    value: '', textContent: '', innerHTML: '', disabled: false,
    classList: {{ add: noop, remove: noop }},
    setAttribute: noop, addEventListener: noop, removeChild: noop, select: noop,
    append(...nodes) {{ this.children.push(...nodes); }},
    appendChild(node) {{ this.children.push(node); return node; }},
  }};
}}
const elements = new Proxy({{}}, {{
  get(target, key) {{ target[key] = target[key] || createElement(String(key)); return target[key]; }}
}});
const sandbox = {{
  console, Date, Object, String, Number, Array, JSON, RegExp, URL,
  navigator: {{}},
  window: {{
    localStorage: {{ getItem() {{ return null; }}, setItem: noop, removeItem: noop }},
    setTimeout,
    clearTimeout,
    open: noop,
  }},
  document: {{
    getElementById(id) {{ return elements[id]; }},
    createElement, body: createElement('body'),
    execCommand() {{ return true; }},
  }},
}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync({json.dumps(str(script_path))}, 'utf8'), sandbox);
{node_body}
"""
        completed = subprocess.run(
            ["node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

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
        self.assertIn("<code>标识|地址</code>", html)
        self.assertIn('class="workbench-layout"', html)
        self.assertIn('class="items-grid items-grid--workbench"', html)
        self.assertIn("/static/js/local_tools.js", html)
        self.assertIn("/static/css/local_tools.css", html)
        self.assertNotIn("管理员", html)

    def test_local_tools_parser_accepts_phone_pipe_url_lines(self):
        payload = self._run_local_tools_node("""
const parsed = sandbox.parseBatchContent(
  '+15722232948|https://example.com/api/get_sms?key=demo\\n' +
  '+15728673707 | https://example.org/api/get_sms?key=demo2\\n' +
  'missing delimiter'
);
process.stdout.write(JSON.stringify({
  count: parsed.items.length,
  invalidCount: parsed.invalidLines.length,
  firstIdentifier: parsed.items[0] && parsed.items[0].identifier,
  firstOpenUrl: parsed.items[0] && parsed.items[0].openUrl,
  firstDisplayUrl: parsed.items[0] && parsed.items[0].displayUrl,
  secondIdentifier: parsed.items[1] && parsed.items[1].identifier,
  invalidReason: parsed.invalidLines[0] && parsed.invalidLines[0].reason,
}));
""")

        self.assertEqual(2, payload["count"])
        self.assertEqual(1, payload["invalidCount"])
        self.assertEqual("+15722232948", payload["firstIdentifier"])
        self.assertEqual("https://example.com/api/get_sms?key=demo", payload["firstOpenUrl"])
        self.assertEqual("https://example.com/api/get_sms", payload["firstDisplayUrl"])
        self.assertEqual("+15728673707", payload["secondIdentifier"])
        self.assertIn("---- 或 |", payload["invalidReason"])

    async def test_local_record_workbench_renders_safe_local_import_page(self):
        response = await local_record_workbench_page(request=self._build_record_request())
        html = response.body.decode("utf-8")

        self.assertIn("本地记录工作台", html)
        self.assertIn("批量导入后形成记录", html)
        self.assertIn("点击姓名、地址、卡号、有效期、CVV 等内容即可复制", html)
        self.assertIn("两种数据合一", html)
        self.assertIn('id="combineRecordDataToggle"', html)
        self.assertIn("开启后可混合导入数据一和数据二", html)
        self.assertIn("手机号|短信接口", html)
        self.assertIn("数据仅保存在当前浏览器本地", html)
        self.assertIn("搜索姓名、地址、卡号、有效期、CVV、电话或标识", html)
        self.assertIn("验证码工具", html)
        self.assertIn('id="recordBatchInput"', html)
        self.assertIn('id="importRecordWorkbenchBtn"', html)
        self.assertIn('id="recordItemsGrid"', html)
        self.assertIn("/static/js/local_records.js", html)
        self.assertIn("/static/css/local_records.css", html)
        self.assertNotIn("<code>姓名----地址</code>", html)
        self.assertNotIn("卡信息----姓名----地址", html)
        self.assertNotIn("单行纯文本", html)
        self.assertNotIn("完整卡号、电话、有效期与附加字段仅本地保存", html)
        self.assertNotIn("附加字段", html)
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
        self.assertIn("label: '卡号'", script)
        self.assertIn("label: '有效期'", script)
        self.assertIn("label: 'CVV'", script)
        self.assertIn("appendVisibleCopyFields", script)
        self.assertIn("record-card__field--wide", script)
        self.assertIn("record-card__copy-value", script)
        self.assertIn("record-card__copy-value", stylesheet)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", stylesheet)
        self.assertIn(".record-workbench-page .panel--import", stylesheet)
        self.assertIn("minmax(260px, 1fr)", stylesheet)
        self.assertIn("#recordBatchInput", stylesheet)
        self.assertIn("record-card__field--wide", stylesheet)
        self.assertNotIn("createRecordButton('复制姓名'", script)
        self.assertNotIn("复制卡尾号", script)
        self.assertNotIn("createCopyField('CVV'", script)
        self.assertIn("toolItem", script)
        self.assertIn("parseLocalToolLine", script)
        self.assertIn("renderLinkedToolItem", script)
        self.assertIn("refreshAndCopyToolItemResult", script)
        self.assertIn("mergeRecordImportResult", script)
        self.assertIn("combineRecordDataToggle", script)
        self.assertIn("record-card__linked-tool", stylesheet)
        self.assertIn("option-toggle", stylesheet)
        self.assertNotIn("createLinkedMetaLine", script)
        self.assertNotIn("record-card__linked-refresh", script)
        self.assertNotIn("record-card__linked-refresh", stylesheet)
        self.assertNotIn("record-card__linked-meta", stylesheet)

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
  URL,
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
        self.assertIn("CVV", payload["renderedText"])
        self.assertIn("987", payload["renderedText"])
        self.assertNotIn("备注", payload["renderedText"])
        self.assertNotIn("短信接口等敏感字段", payload["renderedText"])
        self.assertNotIn("已忽略", payload["renderedText"])
        self.assertNotIn("CVV", " ".join(payload["warnings"]))
        self.assertNotIn("到期日", " ".join(payload["warnings"]))
        self.assertNotIn("https://example.com/api/get_sms", payload["storedValues"])
        self.assertNotIn("key=demo", payload["storedValues"])

    def test_local_record_parser_ignores_leading_unused_payment_prefix(self):
        payload = self._run_local_records_node("""
const parsed = sandbox.parseRecordBatch(
  'KW-EXAMPLE-IGNORE-0001 4111111111111111 ---- 02/30 ---- 902 ---- +15550104567 ---- https://example.com/api/get_sms?key=demo ---- Pat Example ---- 456 Oak Ave, Seattle WA 98101, US'
);
const record = parsed.records[0];
process.stdout.write(JSON.stringify({
  count: parsed.records.length,
  invalidCount: parsed.invalidLines.length,
  cardNumber: record && record.cardNumber,
  cardExpiry: record && record.cardExpiry,
  extraCode: record && record.extraCode,
  phone: record && record.phone,
  name: record && record.name,
  address: record && record.address,
  warnings: record && record.warnings,
  storedValues: [
    record.name,
    record.address,
    record.note,
    record.cardNumber,
    record.cardExpiry,
    record.extraCode,
    record.phone,
    record.warnings.join(' '),
  ].join('|'),
}));
""")

        self.assertEqual(1, payload["count"])
        self.assertEqual(0, payload["invalidCount"])
        self.assertEqual("4111111111111111", payload["cardNumber"])
        self.assertEqual("02/30", payload["cardExpiry"])
        self.assertEqual("902", payload["extraCode"])
        self.assertEqual("+15550104567", payload["phone"])
        self.assertEqual("Pat Example", payload["name"])
        self.assertEqual("456 Oak Ave, Seattle WA 98101, US", payload["address"])
        self.assertIn("已忽略", " ".join(payload["warnings"]))
        self.assertNotIn("KW-EXAMPLE-IGNORE-0001", payload["storedValues"])
        self.assertNotIn("0001", payload["cardNumber"])
        self.assertNotIn("key=demo", payload["storedValues"])

    def test_local_record_parser_requires_combine_option_for_tool_data(self):
        payload = self._run_local_records_node("""
const disabled = sandbox.parseRecordBatch('+15725725788|https://example.com/api/get_sms?key=demo');
const enabled = sandbox.parseRecordBatch('+15725725788|https://example.com/api/get_sms?key=demo', { combineEnabled: true });
process.stdout.write(JSON.stringify({
  disabledCount: disabled.records.length,
  disabledInvalidCount: disabled.invalidLines.length,
  disabledReason: disabled.invalidLines[0] && disabled.invalidLines[0].reason,
  enabledCount: enabled.records.length,
  enabledRecordCount: enabled.recordCount,
  enabledToolItemCount: enabled.toolItemCount,
  enabledIdentifier: enabled.records[0] && enabled.records[0].toolItem && enabled.records[0].toolItem.identifier,
}));
""")

        self.assertEqual(0, payload["disabledCount"])
        self.assertEqual(1, payload["disabledInvalidCount"])
        self.assertIn("开启两种数据合一", payload["disabledReason"])
        self.assertEqual(1, payload["enabledCount"])
        self.assertEqual(0, payload["enabledRecordCount"])
        self.assertEqual(1, payload["enabledToolItemCount"])
        self.assertEqual("+15725725788", payload["enabledIdentifier"])

    def test_local_record_parser_merges_record_and_local_tool_data_by_order(self):
        payload = self._run_local_records_node("""
const parsed = sandbox.parseRecordBatch(
  'JENNIFER WALL----5318 S 105 ST, OMAHA NE 68127, US\\n' +
  '+15725725788|https://example.com/api/get_sms?key=demo\\n' +
  '+15720000000|https://example.org/api/get_sms?key=demo2',
  { combineEnabled: true }
);
const extraRecordParsed = sandbox.parseRecordBatch(
  'JENNIFER WALL----5318 S 105 ST, OMAHA NE 68127, US\\n' +
  'ALEX DEMO----100 Main St, Austin TX 73301, US\\n' +
  '+15725725788|https://example.com/api/get_sms?key=demo',
  { combineEnabled: true }
);
const combined = parsed.records[0];
const extraTool = parsed.records[1];
const extraRecord = extraRecordParsed.records[1];
function collectText(node) {
  if (!node) return '';
  return [node.textContent || '', ...(node.children || []).map(collectText)].join('|');
}
const renderedText = collectText(sandbox.renderRecordCard(combined));
process.stdout.write(JSON.stringify({
  count: parsed.records.length,
  recordCount: parsed.recordCount,
  toolItemCount: parsed.toolItemCount,
  combinedName: combined.name,
  combinedIdentifier: combined.toolItem && combined.toolItem.identifier,
  combinedDisplayUrl: combined.toolItem && combined.toolItem.displayUrl,
  extraToolIdentifier: extraTool.toolItem && extraTool.toolItem.identifier,
  extraToolName: extraTool.name,
  extraRecordName: extraRecord.name,
  extraRecordHasTool: Boolean(extraRecord.toolItem),
  renderedText,
  searchableText: sandbox.buildSearchableRecordText(combined),
}));
""")

        self.assertEqual(2, payload["count"])
        self.assertEqual(1, payload["recordCount"])
        self.assertEqual(2, payload["toolItemCount"])
        self.assertEqual("JENNIFER WALL", payload["combinedName"])
        self.assertEqual("+15725725788", payload["combinedIdentifier"])
        self.assertEqual("https://example.com/api/get_sms", payload["combinedDisplayUrl"])
        self.assertEqual("+15720000000", payload["extraToolIdentifier"])
        self.assertEqual("", payload["extraToolName"])
        self.assertEqual("ALEX DEMO", payload["extraRecordName"])
        self.assertFalse(payload["extraRecordHasTool"])
        self.assertIn("JENNIFER WALL", payload["renderedText"])
        self.assertIn("+15725725788", payload["renderedText"])
        self.assertIn("待刷新", payload["renderedText"])
        self.assertNotIn("来源", payload["renderedText"])
        self.assertNotIn("到期", payload["renderedText"])
        self.assertNotIn("未刷新", payload["renderedText"])
        self.assertNotIn("刷新", payload["renderedText"].replace("待刷新", ""))
        self.assertIn("+15725725788", payload["searchableText"])
        self.assertIn("example.com/api/get_sms", payload["searchableText"])

    def test_local_record_incremental_import_merges_with_existing_records(self):
        payload = self._run_local_records_node("""
const firstImport = sandbox.parseRecordBatch(
  'JENNIFER WALL----5318 S 105 ST, OMAHA NE 68127, US\\n' +
  'ALEX DEMO----100 Main St, Austin TX 73301, US',
  { combineEnabled: true }
);
const afterFirstImport = sandbox.mergeRecordImportResult([], firstImport);
const secondImport = sandbox.parseRecordBatch(
  '+15725725788|https://example.com/api/get_sms?key=demo\\n' +
  '+15720000000|https://example.org/api/get_sms?key=demo2\\n' +
  '+15721111111|https://example.net/api/get_sms?key=demo3',
  { combineEnabled: true }
);
const afterSecondImport = sandbox.mergeRecordImportResult(afterFirstImport, secondImport);
process.stdout.write(JSON.stringify({
  firstCount: afterFirstImport.length,
  secondCount: afterSecondImport.length,
  firstName: afterSecondImport[0] && afterSecondImport[0].name,
  firstIdentifier: afterSecondImport[0] && afterSecondImport[0].toolItem && afterSecondImport[0].toolItem.identifier,
  secondName: afterSecondImport[1] && afterSecondImport[1].name,
  secondIdentifier: afterSecondImport[1] && afterSecondImport[1].toolItem && afterSecondImport[1].toolItem.identifier,
  extraName: afterSecondImport[2] && afterSecondImport[2].name,
  extraIdentifier: afterSecondImport[2] && afterSecondImport[2].toolItem && afterSecondImport[2].toolItem.identifier,
}));
""")

        self.assertEqual(2, payload["firstCount"])
        self.assertEqual(3, payload["secondCount"])
        self.assertEqual("JENNIFER WALL", payload["firstName"])
        self.assertEqual("+15725725788", payload["firstIdentifier"])
        self.assertEqual("ALEX DEMO", payload["secondName"])
        self.assertEqual("+15720000000", payload["secondIdentifier"])
        self.assertEqual("", payload["extraName"])
        self.assertEqual("+15721111111", payload["extraIdentifier"])

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
  URL,
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
