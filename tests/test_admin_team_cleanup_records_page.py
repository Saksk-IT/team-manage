import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import Team, TeamCleanupRecord
from app.routes.admin import team_cleanup_records_page
from app.services.team import TEAM_TYPE_STANDARD


class AdminTeamCleanupRecordsPageTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin/team-cleanup-records", "headers": []})

    async def test_team_cleanup_records_page_renders_cleanup_details(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-cleanup",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Cleanup Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.flush()

            session.add(
                TeamCleanupRecord(
                    team_id=team.id,
                    team_email=team.email,
                    team_name=team.team_name,
                    team_account_id=team.account_id,
                    cleanup_status="partial_failed",
                    removed_member_count=1,
                    revoked_invite_count=1,
                    failed_count=1,
                    removed_member_emails='["removed@example.com"]',
                    revoked_invite_emails='["invite@example.com"]',
                    failed_items='[{"type":"member","email":"failed@example.com","error":"删除失败"}]',
                )
            )
            await session.commit()

            response = await team_cleanup_records_page(
                request=self._build_request(),
                search=None,
                cleanup_status=None,
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("自动清理记录", html)
        self.assertIn("Cleanup Team", html)
        self.assertIn("removed@example.com", html)
        self.assertIn("invite@example.com", html)
        self.assertIn("failed@example.com", html)
        self.assertIn("部分失败", html)
        self.assertIn("搜索 Team、邮箱、Account ID、失败原因", html)


if __name__ == "__main__":
    unittest.main()
