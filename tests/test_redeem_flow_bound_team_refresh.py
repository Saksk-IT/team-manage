import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team
from app.services.redeem_flow import RedeemFlowService
from app.services.team import TEAM_TYPE_STANDARD


class RedeemFlowBoundTeamRefreshTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_verify_code_refreshes_bound_team_before_returning(self):
        service = RedeemFlowService()

        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="enc",
                account_id="acc-1",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Bound Team",
                status="active",
                current_members=1,
                max_members=2,
            )
            session.add(team)
            await session.flush()
            session.add(
                RedemptionCode(
                    code="BOUND-CODE-001",
                    status="unused",
                    bound_team_id=team.id,
                )
            )
            await session.commit()

            async def mock_sync(team_id, db_session, force_refresh=False, progress_callback=None):
                refreshed_team = await db_session.get(Team, team_id)
                refreshed_team.current_members = refreshed_team.max_members
                refreshed_team.status = "full"
                await db_session.commit()
                return {"success": True, "message": "同步成功", "error": None}

            service.team_service.sync_team_info = AsyncMock(side_effect=mock_sync)

            result = await service.verify_code_and_get_teams("BOUND-CODE-001", session)

        self.assertTrue(result["success"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "该兑换码绑定的 Team 已满，请联系管理员处理")
        service.team_service.sync_team_info.assert_awaited_once()

    async def test_redeem_aborts_when_bound_team_refresh_fails(self):
        service = RedeemFlowService()

        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="enc",
                account_id="acc-1",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Bound Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.flush()
            session.add(
                RedemptionCode(
                    code="BOUND-CODE-002",
                    status="unused",
                    bound_team_id=team.id,
                )
            )
            await session.commit()

            service.team_service.sync_team_info = AsyncMock(return_value={
                "success": False,
                "message": None,
                "error": "同步失败"
            })
            service.team_service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.send_invite = AsyncMock(return_value={
                "success": True,
                "data": {"account_invites": [{"id": "invite-1"}]}
            })

            def fake_create_task(coro):
                coro.close()
                return None

            with patch("app.services.redeem_flow.asyncio.create_task", side_effect=fake_create_task):
                result = await service.redeem_and_join_team(
                    email="user@example.com",
                    code="BOUND-CODE-002",
                    team_id=None,
                    db_session=session,
                )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该兑换码绑定的 Team 刷新失败，请稍后重试")
        service.chatgpt_service.send_invite.assert_not_called()


if __name__ == "__main__":
    unittest.main()
