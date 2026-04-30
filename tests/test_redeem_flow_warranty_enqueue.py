import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team, WarrantyEmailEntry
from app.services.redeem_flow import RedeemFlowService
from app.services.team import TEAM_TYPE_STANDARD


class RedeemFlowWarrantyEnqueueTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_redeem_warranty_code_auto_enqueues_email(self):
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
                    code="WARRANTY-CODE-001",
                    status="unused",
                    bound_team_id=team.id,
                    has_warranty=True,
                    warranty_days=30,
                )
            )
            await session.commit()

            service.team_service.refresh_team_state = AsyncMock(return_value={
                "success": True,
                "message": "同步成功",
                "error": None,
            })
            service.team_service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.send_invite = AsyncMock(return_value={
                "success": True,
                "data": {"account_invites": [{"id": "invite-1"}]},
            })

            def fake_create_task(coro):
                coro.close()
                return None

            with patch("app.services.redeem_flow.asyncio.create_task", side_effect=fake_create_task):
                result = await service.redeem_and_join_team(
                    email="buyer@example.com",
                    code="WARRANTY-CODE-001",
                    team_id=None,
                    db_session=session,
                )

            entry = await session.scalar(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == "buyer@example.com")
            )
            code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "WARRANTY-CODE-001")
            )

        self.assertTrue(result["success"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.remaining_claims, 10)
        self.assertEqual(entry.last_redeem_code, "WARRANTY-CODE-001")
        self.assertEqual(entry.source, "auto_redeem")
        self.assertTrue(code.has_warranty)
        self.assertIsNotNone(code.warranty_expires_at)

    async def test_redeem_warranty_code_uses_code_level_remaining_days_and_claims(self):
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
                    code="WARRANTY-CODE-CUSTOM",
                    status="unused",
                    bound_team_id=team.id,
                    has_warranty=True,
                    warranty_days=13,
                    warranty_seconds=12 * 86400 + 3600,
                    warranty_claims=4,
                )
            )
            await session.commit()

            service.team_service.refresh_team_state = AsyncMock(return_value={
                "success": True,
                "message": "同步成功",
                "error": None,
            })
            service.team_service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.send_invite = AsyncMock(return_value={
                "success": True,
                "data": {"account_invites": [{"id": "invite-1"}]},
            })

            def fake_create_task(coro):
                coro.close()
                return None

            with patch("app.services.redeem_flow.asyncio.create_task", side_effect=fake_create_task):
                result = await service.redeem_and_join_team(
                    email="custom@example.com",
                    code="WARRANTY-CODE-CUSTOM",
                    team_id=None,
                    db_session=session,
                )

            entry = await session.scalar(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == "custom@example.com")
            )
            code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "WARRANTY-CODE-CUSTOM")
            )

        self.assertTrue(result["success"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.remaining_claims, 4)
        self.assertEqual(entry.last_redeem_code, "WARRANTY-CODE-CUSTOM")
        self.assertIsNotNone(entry.expires_at)
        self.assertIsNotNone(code.warranty_expires_at)
        remaining_seconds = int((entry.expires_at - code.used_at).total_seconds())
        self.assertGreaterEqual(remaining_seconds, 12 * 86400 + 3595)
        self.assertLessEqual(remaining_seconds, 12 * 86400 + 3605)


if __name__ == "__main__":
    unittest.main()
