import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import AdminUser, RedemptionCode, Team
from app.services.auth import AuthService
from app.services.team import (
    CLASSIFY_TARGET_STANDARD,
    CLASSIFY_TARGET_WARRANTY_CODE,
    CLASSIFY_TARGET_WARRANTY_TEAM,
    IMPORT_STATUS_CLASSIFIED,
    IMPORT_STATUS_PENDING,
    IMPORT_TAG_OTHER_PAID,
    IMPORT_TAG_SELF_PAID,
    TEAM_TYPE_STANDARD,
    TEAM_TYPE_WARRANTY,
    TeamService,
)


class SubAdminAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_create_and_login_sub_admin(self):
        service = AuthService()
        async with self.Session() as session:
            create_result = await service.create_sub_admin("Importer01", "secret123", session)
            login_result = await service.verify_sub_admin_login("importer01", "secret123", session)

        self.assertTrue(create_result["success"])
        self.assertTrue(login_result["success"])
        self.assertEqual(login_result["user"]["role"], "import_admin")
        self.assertFalse(login_result["user"]["is_super_admin"])


class PendingTeamClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.service = TeamService()

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def _create_pending_team(
        self,
        session,
        username="importer01",
        import_tag=None,
        created_at=None,
    ):
        admin = AdminUser(
            username=username,
            password_hash="hash",
            role="import_admin",
            is_active=True,
        )
        session.add(admin)
        await session.flush()
        team_kwargs = {
            "email": f"{username}@example.com",
            "access_token_encrypted": "enc",
            "account_id": f"acc-{username}",
            "team_type": TEAM_TYPE_STANDARD,
            "bound_code_type": TEAM_TYPE_STANDARD,
            "team_name": "Pending Team",
            "status": "active",
            "current_members": 1,
            "max_members": 5,
            "import_status": IMPORT_STATUS_PENDING,
            "imported_by_user_id": admin.id,
            "imported_by_username": admin.username,
            "import_tag": import_tag,
        }
        if created_at is not None:
            team_kwargs["created_at"] = created_at
        team = Team(**team_kwargs)
        session.add(team)
        await session.commit()
        return admin, team

    async def test_pending_team_visibility_can_be_limited_to_importer(self):
        async with self.Session() as session:
            admin1, team1 = await self._create_pending_team(session, "importer01")
            await self._create_pending_team(session, "importer02")

            own_result = await self.service.get_all_teams(
                session,
                import_status=IMPORT_STATUS_PENDING,
                imported_by_user_id=admin1.id,
            )
            all_result = await self.service.get_all_teams(
                session,
                import_status=IMPORT_STATUS_PENDING,
            )

        self.assertTrue(own_result["success"])
        self.assertEqual(own_result["total"], 1)
        self.assertEqual(own_result["teams"][0]["id"], team1.id)
        self.assertEqual(all_result["total"], 2)

    async def test_classify_pending_team_as_standard_generates_no_codes(self):
        async with self.Session() as session:
            _, team = await self._create_pending_team(session)
            result = await self.service.classify_pending_team(
                team.id,
                CLASSIFY_TARGET_STANDARD,
                session,
            )
            codes = (await session.execute(select(RedemptionCode))).scalars().all()
            refreshed = await session.get(Team, team.id)

        self.assertTrue(result["success"])
        self.assertEqual(refreshed.import_status, IMPORT_STATUS_CLASSIFIED)
        self.assertEqual(refreshed.team_type, TEAM_TYPE_STANDARD)
        self.assertEqual(refreshed.bound_code_type, TEAM_TYPE_STANDARD)
        self.assertEqual(len(codes), 0)

    async def test_classify_pending_team_as_warranty_code_compat_goes_to_standard_without_codes(self):
        async with self.Session() as session:
            _, team = await self._create_pending_team(session)
            result = await self.service.classify_pending_team(
                team.id,
                CLASSIFY_TARGET_WARRANTY_CODE,
                session,
                warranty_days=45,
            )
            codes = (await session.execute(select(RedemptionCode))).scalars().all()
            refreshed = await session.get(Team, team.id)

        self.assertTrue(result["success"])
        self.assertEqual(refreshed.import_status, IMPORT_STATUS_CLASSIFIED)
        self.assertEqual(refreshed.team_type, TEAM_TYPE_STANDARD)
        self.assertEqual(refreshed.bound_code_type, TEAM_TYPE_STANDARD)
        self.assertIsNone(refreshed.bound_code_warranty_days)
        self.assertEqual(len(codes), 0)

    async def test_classify_pending_team_as_warranty_team_compat_goes_to_standard(self):
        async with self.Session() as session:
            _, team = await self._create_pending_team(session)
            result = await self.service.classify_pending_team(
                team.id,
                CLASSIFY_TARGET_WARRANTY_TEAM,
                session,
            )
            code_count = await session.scalar(select(func.count(RedemptionCode.id)))
            refreshed = await session.get(Team, team.id)

        self.assertTrue(result["success"])
        self.assertEqual(refreshed.import_status, IMPORT_STATUS_CLASSIFIED)
        self.assertEqual(refreshed.team_type, TEAM_TYPE_STANDARD)
        self.assertEqual(code_count, 0)

    async def test_reviewed_import_record_remains_visible_for_sub_admin_history(self):
        async with self.Session() as session:
            admin, pending_team = await self._create_pending_team(session, "importer01")
            _, reviewed_team = await self._create_pending_team(session, "importer02")
            reviewed_team.imported_by_user_id = admin.id
            reviewed_team.imported_by_username = admin.username
            reviewed_team.import_status = IMPORT_STATUS_CLASSIFIED
            reviewed_team.bound_code_type = TEAM_TYPE_WARRANTY
            await session.commit()

            result = await self.service.get_all_teams(
                session,
                import_status=None,
                imported_by_user_id=admin.id,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 2)
        status_by_id = {team["id"]: team for team in result["teams"]}
        self.assertEqual(status_by_id[pending_team.id]["import_status_label"], "待审核")
        self.assertEqual(status_by_id[reviewed_team.id]["import_status_label"], "已审核")
        self.assertEqual(status_by_id[reviewed_team.id]["import_decision_label"], "控制台 Team")

    async def test_import_history_supports_review_tag_and_date_filters(self):
        async with self.Session() as session:
            _, matched_team = await self._create_pending_team(
                session,
                "importer01",
                import_tag=IMPORT_TAG_OTHER_PAID,
                created_at=datetime(2026, 4, 2, 10, 0, 0),
            )
            _, out_of_range_team = await self._create_pending_team(
                session,
                "importer02",
                import_tag=IMPORT_TAG_OTHER_PAID,
                created_at=datetime(2026, 4, 9, 10, 0, 0),
            )
            _, different_tag_team = await self._create_pending_team(
                session,
                "importer03",
                import_tag=IMPORT_TAG_SELF_PAID,
                created_at=datetime(2026, 4, 2, 10, 0, 0),
            )
            out_of_range_team.import_status = IMPORT_STATUS_CLASSIFIED
            different_tag_team.import_status = IMPORT_STATUS_PENDING
            await session.commit()

            result = await self.service.get_all_teams(
                session,
                import_status=IMPORT_STATUS_PENDING,
                imported_only=True,
                import_tag=IMPORT_TAG_OTHER_PAID,
                imported_from=datetime(2026, 4, 1, 0, 0, 0),
                imported_to=datetime(2026, 4, 3, 23, 59, 59),
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["teams"][0]["id"], matched_team.id)
        self.assertEqual(result["teams"][0]["import_tag"], IMPORT_TAG_OTHER_PAID)
        self.assertEqual(result["teams"][0]["import_tag_label"], "他付")

    async def test_imported_only_history_excludes_super_admin_direct_imports(self):
        async with self.Session() as session:
            _, imported_team = await self._create_pending_team(session, "importer01")
            session.add(
                Team(
                    email="super@example.com",
                    access_token_encrypted="enc",
                    account_id="acc-super",
                    team_type=TEAM_TYPE_STANDARD,
                    bound_code_type=TEAM_TYPE_STANDARD,
                    team_name="Super Admin Team",
                    status="active",
                    current_members=1,
                    max_members=5,
                    import_status=IMPORT_STATUS_CLASSIFIED,
                )
            )
            await session.commit()

            result = await self.service.get_all_teams(
                session,
                import_status=None,
                imported_only=True,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["teams"][0]["id"], imported_team.id)


class SubAdminImportRouteTests(unittest.IsolatedAsyncioTestCase):
    def _build_import_admin_user(self):
        return {
            "id": 7,
            "username": "importer01",
            "is_admin": True,
            "role": "import_admin",
            "is_super_admin": False,
        }

    async def test_sub_admin_single_import_enters_console_without_codes(self):
        from unittest.mock import AsyncMock, patch
        from app.routes.admin import TeamImportRequest, team_import

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
        current_user = self._build_import_admin_user()

        with patch(
            "app.routes.admin.team_service.import_team_single",
            new=AsyncMock(return_value=mocked_result),
        ) as mocked_import:
            response = await team_import(
                import_data=TeamImportRequest(
                    import_type="single",
                    team_type="warranty",
                    access_token="eyJ.payload",
                    generate_warranty_codes=True,
                    warranty_days=45,
                    import_tag=IMPORT_TAG_SELF_PAID,
                ),
                db="db-session",
                current_user=current_user,
            )

        self.assertEqual(response.status_code, 200)
        mocked_import.assert_awaited_once()
        kwargs = mocked_import.await_args.kwargs
        self.assertEqual(kwargs["team_type"], TEAM_TYPE_STANDARD)
        self.assertFalse(kwargs["generate_warranty_codes"])
        self.assertFalse(kwargs["generate_codes_on_import"])
        self.assertEqual(kwargs["import_status"], IMPORT_STATUS_CLASSIFIED)
        self.assertEqual(kwargs["imported_by_user_id"], 7)
        self.assertEqual(kwargs["imported_by_username"], "importer01")
        self.assertEqual(kwargs["import_tag"], IMPORT_TAG_SELF_PAID)

    async def test_sub_admin_batch_import_enters_console_without_codes(self):
        from unittest.mock import patch
        from app.routes.admin import TeamImportRequest, team_import

        async def fake_import_team_batch(**kwargs):
            yield {"type": "finish", "total": 1, "success_count": 1, "failed_count": 0}

        with patch(
            "app.routes.admin.team_service.import_team_batch",
            side_effect=fake_import_team_batch,
        ) as mocked_import_batch:
            response = await team_import(
                import_data=TeamImportRequest(
                    import_type="batch",
                    team_type="warranty",
                    content="eyJ.payload",
                    generate_warranty_codes=True,
                    warranty_days=45,
                    import_tag=IMPORT_TAG_OTHER_PAID,
                ),
                db="db-session",
                current_user=self._build_import_admin_user(),
            )

            body = []
            async for chunk in response.body_iterator:
                body.append(chunk)

        self.assertTrue(body)
        mocked_import_batch.assert_called_once()
        kwargs = mocked_import_batch.call_args.kwargs
        self.assertEqual(kwargs["team_type"], TEAM_TYPE_STANDARD)
        self.assertFalse(kwargs["generate_warranty_codes"])
        self.assertFalse(kwargs["generate_codes_on_import"])
        self.assertEqual(kwargs["import_status"], IMPORT_STATUS_CLASSIFIED)
        self.assertEqual(kwargs["imported_by_user_id"], 7)
        self.assertEqual(kwargs["imported_by_username"], "importer01")
        self.assertEqual(kwargs["import_tag"], IMPORT_TAG_OTHER_PAID)


if __name__ == "__main__":
    unittest.main()
