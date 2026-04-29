import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, WarrantyEmailEntry
from app.services.redemption import RedemptionService


class RedemptionBoundEmailLookupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path}",
            future=True,
        )
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.service = RedemptionService()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_lookup_code_binding_email_returns_bound_email_for_used_code(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="CODE-USED-001",
                    status="used",
                    used_by_email="buyer@example.com",
                    used_at=datetime(2026, 4, 23, 10, 0, 0),
                )
            )
            await session.commit()

            result = await self.service.lookup_code_binding_email("CODE-USED-001", session)

        self.assertTrue(result["success"])
        self.assertTrue(result["found"])
        self.assertTrue(result["bound"])
        self.assertEqual(result["used_by_email"], "buyer@example.com")
        self.assertEqual(result["status"], "used")

    async def test_lookup_code_binding_email_returns_unbound_info_for_unused_code(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="CODE-UNUSED-001",
                    status="unused",
                )
            )
            await session.commit()

            result = await self.service.lookup_code_binding_email("CODE-UNUSED-001", session)

        self.assertTrue(result["success"])
        self.assertTrue(result["found"])
        self.assertFalse(result["bound"])
        self.assertIsNone(result["used_by_email"])
        self.assertEqual(result["status"], "unused")
        self.assertEqual(result["message"], "该兑换码当前未绑定邮箱")

    async def test_withdraw_record_by_code_reuses_withdraw_record_semantics(self):
        async with self.Session() as session:
            code = RedemptionCode(
                code="CODE-WITHDRAW-001",
                status="used",
                used_by_email="buyer@example.com",
                used_team_id=1,
                used_at=datetime(2026, 4, 23, 10, 0, 0),
            )
            session.add(code)
            await session.flush()
            session.add(
                RedemptionRecord(
                    email="buyer@example.com",
                    code=code.code,
                    team_id=1,
                    account_id="acc-1",
                    redeemed_at=datetime(2026, 4, 23, 10, 0, 0),
                )
            )
            await session.commit()

            with patch(
                "app.services.team.team_service.remove_invite_or_member",
                new=AsyncMock(return_value={"success": True, "message": "已移除"})
            ) as mocked_remove:
                result = await self.service.withdraw_record_by_code("CODE-WITHDRAW-001", session)

            code_result = await session.execute(
                select(RedemptionCode).where(RedemptionCode.code == "CODE-WITHDRAW-001")
            )
            refreshed_code = code_result.scalar_one()
            records_result = await session.execute(select(RedemptionRecord))
            remaining_records = records_result.scalars().all()

        mocked_remove.assert_awaited_once_with(1, "buyer@example.com", session)
        self.assertTrue(result["success"])
        self.assertEqual(refreshed_code.status, "unused")
        self.assertIsNone(refreshed_code.used_by_email)
        self.assertIsNone(refreshed_code.used_team_id)
        self.assertIsNone(refreshed_code.used_at)
        self.assertEqual(remaining_records, [])

    async def test_withdraw_record_removes_warranty_email_entry_for_warranty_code(self):
        async with self.Session() as session:
            code = RedemptionCode(
                code="CODE-WARRANTY-WITHDRAW-001",
                status="used",
                has_warranty=True,
                used_by_email="buyer@example.com",
                used_team_id=1,
                used_at=datetime(2026, 4, 23, 11, 0, 0),
            )
            session.add(code)
            await session.flush()
            session.add_all([
                RedemptionRecord(
                    email="buyer@example.com",
                    code=code.code,
                    team_id=1,
                    account_id="acc-warranty",
                    redeemed_at=datetime(2026, 4, 23, 11, 0, 0),
                ),
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=10,
                    source="auto_redeem",
                    last_redeem_code=code.code,
                ),
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    source="manual",
                    last_redeem_code="MANUAL-ORDER-KEEP",
                )
            ])
            await session.commit()

            with patch(
                "app.services.team.team_service.remove_invite_or_member",
                new=AsyncMock(return_value={"success": True, "message": "已移除"})
            ):
                result = await self.service.withdraw_record_by_code("CODE-WARRANTY-WITHDRAW-001", session)

            warranty_result = await session.execute(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == "buyer@example.com")
            )
            warranty_entries = warranty_result.scalars().all()

        self.assertTrue(result["success"])
        self.assertEqual(len(warranty_entries), 1)
        self.assertEqual(warranty_entries[0].last_redeem_code, "MANUAL-ORDER-KEEP")

    async def test_withdraw_record_keeps_warranty_email_entry_for_non_warranty_code(self):
        async with self.Session() as session:
            code = RedemptionCode(
                code="CODE-STANDARD-WITHDRAW-001",
                status="used",
                has_warranty=False,
                used_by_email="buyer@example.com",
                used_team_id=1,
                used_at=datetime(2026, 4, 23, 12, 0, 0),
            )
            session.add(code)
            await session.flush()
            session.add_all([
                RedemptionRecord(
                    email="buyer@example.com",
                    code=code.code,
                    team_id=1,
                    account_id="acc-standard",
                    redeemed_at=datetime(2026, 4, 23, 12, 0, 0),
                ),
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    source="manual",
                    last_redeem_code="OTHER-CODE",
                )
            ])
            await session.commit()

            with patch(
                "app.services.team.team_service.remove_invite_or_member",
                new=AsyncMock(return_value={"success": True, "message": "已移除"})
            ):
                result = await self.service.withdraw_record_by_code("CODE-STANDARD-WITHDRAW-001", session)

            warranty_result = await session.execute(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == "buyer@example.com")
            )
            warranty_entry = warranty_result.scalar_one_or_none()

        self.assertTrue(result["success"])
        self.assertIsNotNone(warranty_entry)
        self.assertEqual(warranty_entry.last_redeem_code, "OTHER-CODE")

    async def test_withdraw_record_by_code_rejects_unbound_code(self):
        async with self.Session() as session:
            session.add(RedemptionCode(code="CODE-UNBOUND-001", status="unused"))
            await session.commit()

            result = await self.service.withdraw_record_by_code("CODE-UNBOUND-001", session)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该兑换码当前未绑定邮箱，无需撤销")


if __name__ == "__main__":
    unittest.main()
