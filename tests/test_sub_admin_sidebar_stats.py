import os
import tempfile
import unittest

from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team
from app.routes.admin import import_only_page
from app.services.team import IMPORT_STATUS_CLASSIFIED, TEAM_TYPE_STANDARD


class SubAdminSidebarStatsTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin/import-only", "headers": []})

    async def test_import_admin_sidebar_renders_console_stats(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="owner@example.com",
                    access_token_encrypted="enc",
                    account_id="acc-1",
                    team_type=TEAM_TYPE_STANDARD,
                    bound_code_type=TEAM_TYPE_STANDARD,
                    team_name="Active Team",
                    status="active",
                    current_members=2,
                    reserved_members=0,
                    max_members=5,
                    import_status=IMPORT_STATUS_CLASSIFIED,
                )
            )
            await session.commit()

            response = await import_only_page(
                request=self._build_request(),
                page=1,
                per_page=20,
                search=None,
                status=None,
                review_status=None,
                import_tag=None,
                imported_from=None,
                imported_to=None,
                db=session,
                current_user={
                    "id": 7,
                    "username": "importer01",
                    "is_admin": True,
                    "role": "import_admin",
                    "is_super_admin": False,
                },
            )

        html = response.body.decode("utf-8")
        self.assertIn("控制台概览", html)
        self.assertIn("Team 总数", html)
        self.assertIn("可用 Team", html)
        self.assertIn("所有席位", html)
        self.assertIn("可用席位", html)
        self.assertIn('<span class="sidebar-stat-value">1</span>', html)
        self.assertIn('<span class="sidebar-stat-value">4</span>', html)
        self.assertIn('<span class="sidebar-stat-value">3</span>', html)


if __name__ == "__main__":
    unittest.main()
