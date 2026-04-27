import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import TeamImportRequest, team_import


class AdminTeamImportWarrantyCodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_import_passes_warranty_code_options(self):
        db_session = object()
        mocked_result = {
            "success": True,
            "team_id": 1,
            "team_ids": [1],
            "email": "owner@example.com",
            "imported_teams": [],
            "generated_codes": [],
            "generated_code_count": 0,
            "message": "ok",
            "error": None,
        }

        with patch(
            "app.routes.admin.team_service.import_team_single",
            new=AsyncMock(return_value=mocked_result),
        ) as mocked_import:
            response = await team_import(
                import_data=TeamImportRequest(
                    import_type="single",
                    team_type="standard",
                    access_token="eyJ.payload",
                    generate_warranty_codes=True,
                    warranty_days=45,
                ),
                db=db_session,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["success"])
        mocked_import.assert_awaited_once_with(
            access_token="eyJ.payload",
            db_session=db_session,
            email=None,
            account_id=None,
            refresh_token=None,
            session_token=None,
            client_id=None,
            team_type="standard",
            generate_warranty_codes=True,
            warranty_days=45,
            import_tag=None,
        )

    async def test_batch_import_passes_warranty_code_options(self):
        async def fake_import_team_batch(**kwargs):
            yield {"type": "finish", "total": 1, "success_count": 1, "failed_count": 0}

        with patch(
            "app.routes.admin.team_service.import_team_batch",
            side_effect=fake_import_team_batch,
        ) as mocked_import_batch:
            response = await team_import(
                import_data=TeamImportRequest(
                    import_type="batch",
                    team_type="standard",
                    content="eyJ.payload",
                    generate_warranty_codes=True,
                    warranty_days=45,
                ),
                db="db-session",
                current_user={"username": "admin"},
            )

            body = []
            async for chunk in response.body_iterator:
                body.append(chunk)

        self.assertTrue(body)
        mocked_import_batch.assert_called_once_with(
            text="eyJ.payload",
            db_session="db-session",
            team_type="standard",
            generate_warranty_codes=True,
            warranty_days=45,
            import_tag=None,
        )


if __name__ == "__main__":
    unittest.main()
