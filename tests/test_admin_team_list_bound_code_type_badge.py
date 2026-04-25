import os
import re
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import Team
from app.routes.admin import admin_dashboard, warranty_teams_dashboard


class AdminTeamListBoundCodeTypeBadgeTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin", "headers": []})

    async def test_team_list_renders_warranty_badge_for_warranty_bound_code_team(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="warranty-owner@example.com",
                    access_token_encrypted="dummy-token",
                    account_id="acc-warranty",
                    team_name="Warranty Badge Team",
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
        self.assertIn("账号类型", html)
        self.assertRegex(html, r"<td>\s*Warranty Badge Team\s*</td>\s*<td>\s*<span[^>]*data-bound-code-type=\"warranty\"")
        self.assertRegex(html, r'data-bound-code-type="warranty"[^>]*>\s*质保\s*<')
        self.assertIn("质保 15 天", html)

    async def test_team_list_renders_standard_badge_for_standard_bound_code_team(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="standard-owner@example.com",
                    access_token_encrypted="dummy-token",
                    account_id="acc-standard",
                    team_name="Standard Badge Team",
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
        self.assertIn("账号类型", html)
        self.assertRegex(html, r"<td>\s*Standard Badge Team\s*</td>\s*<td>\s*<span[^>]*data-bound-code-type=\"standard\"")
        self.assertRegex(html, r'data-bound-code-type="standard"[^>]*>\s*普通\s*<')

    async def test_warranty_team_list_renders_unavailable_badge_for_marked_team(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="warranty-owner@example.com",
                    access_token_encrypted="dummy-token",
                    account_id="acc-warranty",
                    team_type="warranty",
                    team_name="Unavailable Warranty Team",
                    status="error",
                    current_members=1,
                    max_members=5,
                    warranty_unavailable=True,
                    warranty_unavailable_reason="官方拦截下发(响应空列表)",
                )
            )
            await session.commit()

            response = await warranty_teams_dashboard(
                request=Request({"type": "http", "method": "GET", "path": "/admin/warranty-teams", "headers": []}),
                page=1,
                per_page=20,
                search=None,
                status=None,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("Unavailable Warranty Team", html)
        self.assertIn("已标记不可用", html)
        self.assertRegex(html, r'>\s*不可用\s*<')


if __name__ == "__main__":
    unittest.main()
