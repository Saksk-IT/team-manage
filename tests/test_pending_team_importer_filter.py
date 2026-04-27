import os
import tempfile
import unittest

from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import AdminUser, Team
from app.routes.admin import pending_teams_dashboard
from app.services.team import IMPORT_STATUS_PENDING, TEAM_TYPE_STANDARD


class PendingTeamImporterFilterTests(unittest.IsolatedAsyncioTestCase):
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

    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/pending-teams", "headers": []})

    async def _seed_importers_and_teams(self, session):
        importer1 = AdminUser(username="importer01", password_hash="hash", role="import_admin", is_active=True)
        importer2 = AdminUser(username="importer02", password_hash="hash", role="import_admin", is_active=True)
        session.add_all([importer1, importer2])
        await session.flush()

        session.add_all([
            Team(
                email="team-a@example.com",
                access_token_encrypted="enc",
                account_id="acc-a",
                team_type=TEAM_TYPE_STANDARD,
                bound_code_type=TEAM_TYPE_STANDARD,
                team_name="Team A",
                status="active",
                current_members=1,
                max_members=5,
                import_status=IMPORT_STATUS_PENDING,
                imported_by_user_id=importer1.id,
                imported_by_username=importer1.username,
            ),
            Team(
                email="team-b@example.com",
                access_token_encrypted="enc",
                account_id="acc-b",
                team_type=TEAM_TYPE_STANDARD,
                bound_code_type=TEAM_TYPE_STANDARD,
                team_name="Team B",
                status="active",
                current_members=1,
                max_members=5,
                import_status=IMPORT_STATUS_PENDING,
                imported_by_user_id=importer2.id,
                imported_by_username=importer2.username,
            ),
        ])
        await session.commit()
        return importer1, importer2

    async def test_pending_teams_page_renders_importer_filter_options(self):
        async with self.Session() as session:
            importer1, importer2 = await self._seed_importers_and_teams(session)
            response = await pending_teams_dashboard(
                request=self._build_request(),
                page=1,
                per_page=20,
                search=None,
                status=None,
                review_status=None,
                import_tag=None,
                imported_by_user_id=None,
                imported_from=None,
                imported_to=None,
                db=session,
                current_user={"username": "admin", "is_admin": True, "is_super_admin": True},
            )

        html = response.body.decode("utf-8")
        self.assertIn('name="imported_by_user_id"', html)
        self.assertIn("全部导入人", html)
        self.assertIn(f'value="{importer1.id}"', html)
        self.assertIn(f'value="{importer2.id}"', html)
        self.assertIn("importer01", html)
        self.assertIn("importer02", html)

    async def test_pending_teams_page_filters_by_importer(self):
        async with self.Session() as session:
            importer1, _ = await self._seed_importers_and_teams(session)
            response = await pending_teams_dashboard(
                request=self._build_request(),
                page=1,
                per_page=20,
                search=None,
                status=None,
                review_status=None,
                import_tag=None,
                imported_by_user_id=importer1.id,
                imported_from=None,
                imported_to=None,
                db=session,
                current_user={"username": "admin", "is_admin": True, "is_super_admin": True},
            )

        html = response.body.decode("utf-8")
        self.assertIn("team-a@example.com", html)
        self.assertNotIn("team-b@example.com", html)
        self.assertIn(f'<option value="{importer1.id}" selected>', html)


if __name__ == "__main__":
    unittest.main()
