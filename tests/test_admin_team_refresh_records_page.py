import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import Team, TeamRefreshRecord
from app.routes.admin import team_refresh_records_page
from app.services.team import TEAM_TYPE_STANDARD


class AdminTeamRefreshRecordsPageTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin/team-refresh-records", "headers": []})

    async def test_team_refresh_records_page_renders_filters_and_result_details(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-refresh",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Refresh Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.flush()

            session.add(
                TeamRefreshRecord(
                    team_id=team.id,
                    team_email=team.email,
                    team_name=team.team_name,
                    team_account_id=team.account_id,
                    source="user_redeem",
                    refresh_status="failed",
                    force_refresh=False,
                    team_status="error",
                    current_members=1,
                    max_members=5,
                    error="Token 已过期",
                    error_code="token_refresh_failed",
                    cleanup_removed_member_count=1,
                    cleanup_revoked_invite_count=0,
                    cleanup_failed_count=0,
                )
            )
            await session.commit()

            response = await team_refresh_records_page(
                request=self._build_request(),
                search=None,
                source=None,
                refresh_status=None,
                team_status=None,
                has_cleanup=None,
                start_date=None,
                end_date=None,
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("Team 刷新记录", html)
        self.assertIn("Refresh Team", html)
        self.assertIn("前台兑换", html)
        self.assertIn("刷新失败", html)
        self.assertIn("Token 已过期", html)
        self.assertIn("自动清理：1", html)
        self.assertIn("刷新总数", html)
        self.assertIn("刷新成功", html)
        self.assertIn("刷新失败", html)
        self.assertIn("含自动清理", html)
        self.assertIn("数据来源", html)


if __name__ == "__main__":
    unittest.main()
