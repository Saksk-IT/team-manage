import os
import tempfile
import unittest
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team
from app.services.team import TEAM_TYPE_WARRANTY, TeamService


class TeamAddMemberRetryFlagsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_add_team_member_marks_seat_limit_error_as_retryable(self):
        async with self.Session() as session:
            team = Team(
                email="warranty-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team",
                status="active",
                current_members=3,
                max_members=5,
            )
            session.add(team)
            await session.commit()

            service = TeamService()
            service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service.ensure_access_token = AsyncMock(return_value="token")
            service.chatgpt_service.send_invite = AsyncMock(
                return_value={
                    "success": False,
                    "error": "Workspace has reached maximum number of seats allowed for a free trial.",
                }
            )

            result = await service.add_team_member(team.id, "buyer@example.com", session)
            refreshed_team = await session.get(Team, team.id)

        self.assertFalse(result["success"])
        self.assertTrue(result["allow_try_next_team"])
        self.assertIn("maximum number of seats", result["error"].lower())
        self.assertEqual(refreshed_team.status, "full")
        self.assertTrue(refreshed_team.warranty_unavailable)
        self.assertIn("maximum number of seats", (refreshed_team.warranty_unavailable_reason or "").lower())

    async def test_add_team_member_marks_intercepted_invite_error_as_warranty_unavailable(self):
        async with self.Session() as session:
            team = Team(
                email="warranty-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team",
                status="active",
                current_members=2,
                max_members=5,
            )
            session.add(team)
            await session.commit()

            service = TeamService()
            service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service.ensure_access_token = AsyncMock(return_value="token")
            service.chatgpt_service.send_invite = AsyncMock(
                return_value={
                    "success": True,
                    "data": {"account_invites": []},
                }
            )

            result = await service.add_team_member(team.id, "buyer@example.com", session)
            refreshed_team = await session.get(Team, team.id)

        self.assertFalse(result["success"])
        self.assertTrue(result["allow_try_next_team"])
        self.assertEqual(result["error_code"], "invite_intercepted_empty_list")
        self.assertEqual(refreshed_team.status, "error")
        self.assertTrue(refreshed_team.warranty_unavailable)
        self.assertEqual(
            refreshed_team.warranty_unavailable_reason,
            "官方拦截下发(响应空列表)"
        )
