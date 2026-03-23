import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, Setting, Team
from app.services.settings import settings_service
from app.services.team import TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY
from app.services.warranty import WarrantyService


class WarrantyClaimTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        settings_service.clear_cache()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        settings_service.clear_cache()
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def _seed_base_data(self, session):
        ordinary_team = Team(
            email="ordinary-owner@example.com",
            access_token_encrypted="dummy",
            account_id="acc-ordinary",
            team_type=TEAM_TYPE_STANDARD,
            team_name="Ordinary Team",
            status="active",
            current_members=2,
            max_members=5
        )
        warranty_team = Team(
            email="warranty-owner@example.com",
            access_token_encrypted="dummy",
            account_id="acc-warranty",
            team_type=TEAM_TYPE_WARRANTY,
            team_name="Warranty Team",
            status="active",
            current_members=1,
            max_members=5
        )
        session.add_all([
            ordinary_team,
            warranty_team,
            Setting(key="warranty_super_code", value="SUPER-CODE-1234")
        ])
        await session.flush()
        return ordinary_team, warranty_team

    async def test_claim_warranty_success_creates_record(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_base_data(session)
            session.add(
                RedemptionCode(
                    code="CODE-123",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.get_team_members = AsyncMock(return_value={"success": True, "members": []})
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-123",
                email="buyer@example.com",
                super_code="SUPER-CODE-1234"
            )

            record_count_result = await session.execute(
                select(func.count(RedemptionRecord.id)).where(
                    RedemptionRecord.code == "CODE-123",
                    RedemptionRecord.email == "buyer@example.com",
                    RedemptionRecord.team_id == warranty_team.id,
                    RedemptionRecord.is_warranty_redemption.is_(True)
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["team_info"]["id"], warranty_team.id)
        self.assertEqual(record_count_result.scalar(), 1)

    async def test_claim_warranty_falls_back_to_latest_record_email(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_base_data(session)
            session.add(
                RedemptionCode(
                    code="CODE-456",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email=None,
                    used_team_id=ordinary_team.id
                )
            )
            session.add(
                RedemptionRecord(
                    email="history@example.com",
                    code="CODE-456",
                    team_id=ordinary_team.id,
                    account_id=ordinary_team.account_id,
                    redeemed_at=datetime.now() - timedelta(days=1)
                )
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.get_team_members = AsyncMock(return_value={"success": True, "members": []})
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-456",
                email="history@example.com",
                super_code="SUPER-CODE-1234"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["team_info"]["id"], warranty_team.id)

    async def test_claim_warranty_wrong_super_code_returns_generic_error(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_base_data(session)
            session.add(
                RedemptionCode(
                    code="CODE-789",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.get_team_members = AsyncMock()
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-789",
                email="buyer@example.com",
                super_code="WRONG-CODE"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], service.CLAIM_GENERIC_ERROR)
        service.team_service.add_team_member.assert_not_awaited()

    async def test_claim_warranty_is_idempotent_when_member_already_exists(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_base_data(session)
            session.add(
                RedemptionCode(
                    code="CODE-999",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.get_team_members = AsyncMock(return_value={
                "success": True,
                "members": [{"email": "buyer@example.com", "status": "joined"}]
            })
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-999",
                email="buyer@example.com",
                super_code="SUPER-CODE-1234"
            )

            record_count_result = await session.execute(
                select(func.count(RedemptionRecord.id)).where(
                    RedemptionRecord.code == "CODE-999",
                    RedemptionRecord.email == "buyer@example.com",
                    RedemptionRecord.team_id == warranty_team.id,
                    RedemptionRecord.is_warranty_redemption.is_(True)
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(record_count_result.scalar(), 1)
        service.team_service.add_team_member.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
