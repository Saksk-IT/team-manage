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

    async def _seed_base_data(
        self,
        session,
        usage_code="",
        usage_limit=2,
        time_code="",
        time_days=15
    ):
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
            Setting(key=settings_service.WARRANTY_USAGE_LIMIT_SUPER_CODE_KEY, value=usage_code),
            Setting(key=settings_service.WARRANTY_USAGE_LIMIT_MAX_USES_KEY, value=str(usage_limit) if usage_code else ""),
            Setting(key=settings_service.WARRANTY_TIME_LIMIT_SUPER_CODE_KEY, value=time_code),
            Setting(key=settings_service.WARRANTY_TIME_LIMIT_DAYS_KEY, value=str(time_days) if time_code else ""),
        ])
        await session.flush()
        return ordinary_team, warranty_team

    async def test_usage_limit_super_code_success_creates_record(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_base_data(
                session,
                usage_code="USAGE-CODE-1234",
                usage_limit=2
            )
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
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-123",
                email="buyer@example.com",
                super_code="usage-code-1234"
            )

            record_result = await session.execute(
                select(RedemptionRecord).where(
                    RedemptionRecord.code == "CODE-123",
                    RedemptionRecord.email == "buyer@example.com",
                    RedemptionRecord.team_id == warranty_team.id
                )
            )
            record = record_result.scalar_one()

        self.assertTrue(result["success"])
        self.assertEqual(record.warranty_super_code_type, settings_service.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT)

    async def test_usage_limit_super_code_respects_max_uses(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_base_data(
                session,
                usage_code="USAGE-CODE-1234",
                usage_limit=2
            )
            session.add(
                RedemptionCode(
                    code="CODE-LIMIT",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            session.add_all([
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-LIMIT",
                    team_id=warranty_team.id,
                    account_id=warranty_team.account_id,
                    is_warranty_redemption=True,
                    warranty_super_code_type=settings_service.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT
                ),
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-LIMIT",
                    team_id=warranty_team.id,
                    account_id=warranty_team.account_id,
                    is_warranty_redemption=True,
                    warranty_super_code_type=settings_service.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT
                )
            ])
            await session.commit()

            service = WarrantyService()
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-LIMIT",
                email="buyer@example.com",
                super_code="USAGE-CODE-1234"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], service.CLAIM_GENERIC_ERROR)
        service.team_service.add_team_member.assert_not_awaited()

    async def test_time_limit_super_code_uses_first_used_at(self):
        now = datetime.now()
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_base_data(
                session,
                time_code="TIME-CODE-1234",
                time_days=15
            )
            session.add(
                RedemptionCode(
                    code="CODE-TIME",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id,
                    used_at=now - timedelta(days=5)
                )
            )
            await session.commit()

            service = WarrantyService()
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-TIME",
                email="buyer@example.com",
                super_code="TIME-CODE-1234"
            )

            record_result = await session.execute(
                select(RedemptionRecord).where(
                    RedemptionRecord.code == "CODE-TIME",
                    RedemptionRecord.team_id == warranty_team.id
                )
            )
            record = record_result.scalar_one()

        self.assertTrue(result["success"])
        self.assertEqual(record.warranty_super_code_type, settings_service.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT)

    async def test_time_limit_super_code_falls_back_to_first_non_warranty_record(self):
        now = datetime.now()
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_base_data(
                session,
                time_code="TIME-CODE-1234",
                time_days=15
            )
            session.add(
                RedemptionCode(
                    code="CODE-FALLBACK",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email=None,
                    used_team_id=ordinary_team.id,
                    used_at=None
                )
            )
            session.add(
                RedemptionRecord(
                    email="history@example.com",
                    code="CODE-FALLBACK",
                    team_id=ordinary_team.id,
                    account_id=ordinary_team.account_id,
                    redeemed_at=now - timedelta(days=7),
                    is_warranty_redemption=False
                )
            )
            await session.commit()

            service = WarrantyService()
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-FALLBACK",
                email="history@example.com",
                super_code="TIME-CODE-1234"
            )

        self.assertTrue(result["success"])

    async def test_time_limit_super_code_fails_when_expired(self):
        now = datetime.now()
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_base_data(
                session,
                time_code="TIME-CODE-1234",
                time_days=15
            )
            session.add(
                RedemptionCode(
                    code="CODE-EXPIRED",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id,
                    used_at=now - timedelta(days=20)
                )
            )
            await session.commit()

            service = WarrantyService()
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-EXPIRED",
                email="buyer@example.com",
                super_code="TIME-CODE-1234"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], service.CLAIM_GENERIC_ERROR)
        service.team_service.add_team_member.assert_not_awaited()

    async def test_time_limit_super_code_fails_without_any_first_use_timestamp(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_base_data(
                session,
                time_code="TIME-CODE-1234",
                time_days=15
            )
            session.add(
                RedemptionCode(
                    code="CODE-NO-TIME",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id,
                    used_at=None
                )
            )
            await session.commit()

            service = WarrantyService()
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-NO-TIME",
                email="buyer@example.com",
                super_code="TIME-CODE-1234"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], service.CLAIM_GENERIC_ERROR)

    async def test_claim_warranty_wrong_super_code_returns_generic_error(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_base_data(
                session,
                usage_code="USAGE-CODE-1234",
                usage_limit=2
            )
            session.add(
                RedemptionCode(
                    code="CODE-WRONG",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            service = WarrantyService()
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-WRONG",
                email="buyer@example.com",
                super_code="WRONG-CODE"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], service.CLAIM_GENERIC_ERROR)
        service.team_service.add_team_member.assert_not_awaited()

    async def test_claim_warranty_is_idempotent_when_member_already_exists_and_does_not_count(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_base_data(
                session,
                usage_code="USAGE-CODE-1234",
                usage_limit=2
            )
            session.add(
                RedemptionCode(
                    code="CODE-IDEMPOTENT",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            service = WarrantyService()
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=warranty_team)
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                ordinary_code="CODE-IDEMPOTENT",
                email="buyer@example.com",
                super_code="USAGE-CODE-1234"
            )

            record_count_result = await session.execute(
                select(func.count(RedemptionRecord.id)).where(
                    RedemptionRecord.code == "CODE-IDEMPOTENT",
                    RedemptionRecord.email == "buyer@example.com",
                    RedemptionRecord.team_id == warranty_team.id,
                    RedemptionRecord.is_warranty_redemption.is_(True)
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(record_count_result.scalar(), 0)
        service.team_service.add_team_member.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
