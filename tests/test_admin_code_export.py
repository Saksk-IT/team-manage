import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.routes.admin import CodeExportRequest, _build_codes_export_response


class AdminCodeExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_export_returns_one_code_per_line_and_selected_scope(self):
        db_session = object()
        mocked_result = {
            "success": True,
            "codes": [
                {"code": "CODE-001", "status": "unused"},
                {"code": "CODE-002", "status": "used"},
            ],
        }

        with patch(
            "app.routes.admin.redemption_service.get_all_codes",
            new=AsyncMock(return_value=mocked_result)
        ) as mocked_get_all_codes:
            response = await _build_codes_export_response(
                CodeExportRequest(
                    codes=["CODE-001", "CODE-002"],
                    search="ignored",
                    status_filter="used",
                    export_format="text",
                ),
                db=db_session,
            )

        self.assertEqual(response.headers["content-type"], "text/plain; charset=utf-8")
        self.assertEqual(response.body.decode("utf-8"), "CODE-001\nCODE-002")
        mocked_get_all_codes.assert_awaited_once_with(
            db_session,
            page=1,
            per_page=100000,
            search=None,
            status=None,
            selected_codes=["CODE-001", "CODE-002"],
            bound_team_id=None,
            bound_team_ids=None,
        )

    async def test_excel_export_returns_excel_media_type(self):
        db_session = object()
        mocked_result = {
            "success": True,
            "codes": [
                {
                    "code": "CODE-001",
                    "status": "unused",
                    "created_at": "2026-03-22T10:00:00",
                    "expires_at": None,
                    "used_by_email": None,
                    "used_at": None,
                    "has_warranty": False,
                    "warranty_days": 30,
                }
            ],
        }

        with patch(
            "app.routes.admin.redemption_service.get_all_codes",
            new=AsyncMock(return_value=mocked_result)
        ):
            response = await _build_codes_export_response(
                CodeExportRequest(export_format="excel"),
                db=db_session,
            )

        self.assertEqual(
            response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(response.body.startswith(b"PK"))

    async def test_team_export_scope_passes_bound_team_id(self):
        db_session = object()
        mocked_result = {
            "success": True,
            "codes": [
                {"code": "TEAM-CODE-001", "status": "unused"},
            ],
        }

        with patch(
            "app.routes.admin.redemption_service.get_all_codes",
            new=AsyncMock(return_value=mocked_result)
        ) as mocked_get_all_codes:
            response = await _build_codes_export_response(
                CodeExportRequest(team_id=7, export_format="text"),
                db=db_session,
            )

        self.assertEqual(response.body.decode("utf-8"), "TEAM-CODE-001")
        mocked_get_all_codes.assert_awaited_once_with(
            db_session,
            page=1,
            per_page=100000,
            search=None,
            status=None,
            selected_codes=None,
            bound_team_id=7,
            bound_team_ids=None,
        )

    async def test_multi_team_export_scope_passes_bound_team_ids(self):
        db_session = object()
        mocked_result = {
            "success": True,
            "codes": [
                {"code": "TEAM-CODE-001", "status": "unused"},
                {"code": "TEAM-CODE-002", "status": "unused"},
            ],
        }

        with patch(
            "app.routes.admin.redemption_service.get_all_codes",
            new=AsyncMock(return_value=mocked_result)
        ) as mocked_get_all_codes:
            response = await _build_codes_export_response(
                CodeExportRequest(team_ids=[7, 9], export_format="text"),
                db=db_session,
            )

        self.assertEqual(response.body.decode("utf-8"), "TEAM-CODE-001\nTEAM-CODE-002")
        mocked_get_all_codes.assert_awaited_once_with(
            db_session,
            page=1,
            per_page=100000,
            search=None,
            status=None,
            selected_codes=None,
            bound_team_id=None,
            bound_team_ids=[7, 9],
        )

    async def test_invalid_export_format_raises_bad_request(self):
        with self.assertRaises(HTTPException) as context:
            await _build_codes_export_response(
                CodeExportRequest(export_format="json"),
                db=object(),
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "不支持的导出格式")


if __name__ == "__main__":
    unittest.main()
