import ast
import unittest
from pathlib import Path


class TemplateResponseSignatureTests(unittest.TestCase):
    def test_template_response_calls_pass_request_first(self):
        repo_root = Path(__file__).resolve().parent.parent
        target_files = [
            repo_root / "app" / "main.py",
            repo_root / "app" / "routes" / "user.py",
            repo_root / "app" / "routes" / "admin.py",
        ]

        invalid_calls: list[str] = []

        for file_path in target_files:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute) or node.func.attr != "TemplateResponse":
                    continue

                first_arg = node.args[0] if node.args else None
                if not isinstance(first_arg, ast.Name) or first_arg.id != "request":
                    invalid_calls.append(f"{file_path}:{node.lineno}")

        self.assertEqual(
            [],
            invalid_calls,
            "TemplateResponse 调用必须把 request 作为第一个位置参数，以兼容当前 Starlette/FastAPI 版本。",
        )


if __name__ == "__main__":
    unittest.main()
