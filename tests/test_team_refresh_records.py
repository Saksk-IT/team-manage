import os
import tempfile
import unittest
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team, TeamRefreshRecord
from app.services.team import TeamService, TEAM_TYPE_STANDARD
from app.services.team_refresh_record import team_refresh_record_service


class TeamRefreshRecordTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_team(self) -> int:
        async with self.Session() as session:
            team = Team(
                email="refresh-owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-refresh",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Refresh Team",
                status="active",
                current_members=2,
                max_members=5,
            )
            session.add(team)
            await session.commit()
            return team.id

    async def test_refresh_team_state_records_source_result_and_resets_timer(self):
        team_id = await self._create_team()
        service = TeamService()
        service.sync_team_info = AsyncMock(return_value={
            "success": True,
            "message": "同步成功,当前成员数: 3",
            "member_emails": ["a@example.com"],
            "cleanup_record_id": 9,
            "cleanup_removed_member_count": 1,
            "cleanup_revoked_invite_count": 0,
            "cleanup_failed_count": 0,
            "error": None,
        })

        async with self.Session() as session:
            result = await service.refresh_team_state(
                team_id,
                session,
                force_refresh=True,
                source="admin_manual",
            )
            await session.commit()

        async with self.Session() as session:
            refreshed_team = await session.get(Team, team_id)
            record = await session.scalar(
                select(TeamRefreshRecord).where(TeamRefreshRecord.team_id == team_id)
            )

        self.assertTrue(result["success"])
        self.assertIsNotNone(refreshed_team.last_refresh_at)
        self.assertIsNotNone(record)
        self.assertEqual(record.source, "admin_manual")
        self.assertEqual(record.refresh_status, "success")
        self.assertTrue(record.force_refresh)
        self.assertEqual(record.team_status, "active")
        self.assertEqual(record.cleanup_record_id, 9)
        self.assertEqual(record.cleanup_removed_member_count, 1)

    async def test_list_refresh_records_supports_multiple_filters(self):
        team_id = await self._create_team()

        async with self.Session() as session:
            session.add_all([
                TeamRefreshRecord(
                    team_id=team_id,
                    team_email="refresh-owner@example.com",
                    team_name="Refresh Team",
                    team_account_id="acc-refresh",
                    source="auto",
                    refresh_status="success",
                    force_refresh=False,
                    team_status="active",
                    current_members=2,
                    max_members=5,
                    message="同步成功",
                    cleanup_removed_member_count=0,
                    cleanup_revoked_invite_count=0,
                    cleanup_failed_count=0,
                ),
                TeamRefreshRecord(
                    team_id=team_id,
                    team_email="refresh-owner@example.com",
                    team_name="Refresh Team",
                    team_account_id="acc-refresh",
                    source="user_redeem",
                    refresh_status="failed",
                    force_refresh=False,
                    team_status="error",
                    error="Token 已过期",
                    error_code="token_refresh_failed",
                    cleanup_removed_member_count=0,
                    cleanup_revoked_invite_count=0,
                    cleanup_failed_count=0,
                ),
            ])
            await session.commit()

            result = await team_refresh_record_service.list_refresh_records(
                session,
                search="refresh-owner",
                source="user_redeem",
                refresh_status="failed",
                team_status="error",
                has_cleanup="without_cleanup",
                page=1,
                per_page=20,
            )

        self.assertEqual(result["pagination"]["total"], 1)
        self.assertEqual(result["records"][0]["source"], "user_redeem")
        self.assertEqual(result["records"][0]["refresh_status_label"], "刷新失败")


if __name__ == "__main__":
    unittest.main()
