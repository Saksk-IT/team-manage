import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, Team, WarrantyEmailEntry
from app.services.team import TEAM_TYPE_STANDARD
from app.services.warranty import WarrantyService
from app.utils.time_utils import get_now


class WarrantyFakeSuccessValidationTests(unittest.IsolatedAsyncioTestCase):
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

    async def _add_latest_team_record(self, session, email: str, team_status: str = "banned"):
        team = Team(
            email="ordinary-owner@example.com",
            access_token_encrypted="dummy",
            account_id="acc-ordinary",
            team_type=TEAM_TYPE_STANDARD,
            team_name="Ordinary Team",
            status=team_status,
            current_members=2,
            max_members=5
        )
        session.add(team)
        await session.flush()
        session.add(RedemptionCode(code="CODE-123", status="used"))
        session.add(
            RedemptionRecord(
                email=email,
                code="CODE-123",
                team_id=team.id,
                account_id=team.account_id,
                redeemed_at=get_now()
            )
        )

    async def test_validate_warranty_claim_input_success(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual"
                )
            )
            await self._add_latest_team_record(session, "buyer@example.com", team_status="banned")
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["normalized_email"], "buyer@example.com")

    async def test_validate_warranty_claim_input_rejects_missing_email_entry(self):
        async with self.Session() as session:
            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该邮箱不在质保邮箱列表中")

    async def test_validate_warranty_claim_input_rejects_zero_claims(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=0,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual"
                )
            )
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该邮箱暂无可用质保次数")

    async def test_validate_warranty_claim_input_rejects_inactive_expiry(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=None,
                    source="manual"
                )
            )
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该邮箱质保资格未启用")

    async def test_validate_warranty_claim_input_rejects_active_latest_team_when_banned_required(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual"
                )
            )
            await self._add_latest_team_record(session, "buyer@example.com", team_status="active")
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={
                "success": True,
                "member_emails": ["buyer@example.com"],
            })
            result = await service.validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com",
                require_latest_team_banned=True
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该质保订单最近加入的 Team 当前状态为「可用」，只有封禁状态才可以提交质保。")


if __name__ == "__main__":
    unittest.main()
