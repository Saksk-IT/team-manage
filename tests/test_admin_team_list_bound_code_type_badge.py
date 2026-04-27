import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import Team
from app.routes.admin import admin_dashboard, warranty_teams_dashboard


class AdminTeamListUnifiedPoolTests(unittest.IsolatedAsyncioTestCase):
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

    def _build_request(self, path: str = "/admin") -> Request:
        return Request({"type": "http", "method": "GET", "path": path, "headers": []})

    async def test_team_list_no_longer_renders_bound_code_type_badge(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="owner@example.com",
                    access_token_encrypted="dummy-token",
                    account_id="acc-standard",
                    team_name="Unified Pool Team",
                    bound_code_type="warranty",
                    bound_code_warranty_days=15,
                    status="active",
                    current_members=1,
                    max_members=5,
                )
            )
            await session.commit()

            response = await admin_dashboard(
                request=self._build_request(),
                page=1,
                per_page=20,
                search=None,
                status=None,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("Unified Pool Team", html)
        self.assertNotIn("账号类型", html)
        self.assertNotIn("data-bound-code-type", html)
        self.assertNotIn("质保 15 天", html)

    async def test_team_list_renders_unavailable_badge_in_console(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="owner@example.com",
                    access_token_encrypted="dummy-token",
                    account_id="acc-unavailable",
                    team_name="Unavailable Unified Team",
                    status="active",
                    current_members=1,
                    max_members=5,
                    warranty_unavailable=True,
                    warranty_unavailable_reason="官方拦截下发(响应空列表)",
                )
            )
            await session.commit()

            response = await admin_dashboard(
                request=self._build_request(),
                page=1,
                per_page=20,
                search=None,
                status=None,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("Unavailable Unified Team", html)
        self.assertIn("已标记不可用", html)
        self.assertRegex(html, r'>\s*不可用\s*<')

    async def test_legacy_warranty_team_url_redirects_to_console(self):
        response = await warranty_teams_dashboard(
            request=self._build_request("/admin/warranty-teams"),
            current_user={"username": "admin"},
        )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/admin")


if __name__ == "__main__":
    unittest.main()
