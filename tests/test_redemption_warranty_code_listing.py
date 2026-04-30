import os
import tempfile
import unittest
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, WarrantyEmailEntry
from app.services.redemption import RedemptionService
from app.utils.time_utils import get_now


class RedemptionWarrantyCodeListingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.service = RedemptionService()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_get_all_codes_includes_synced_warranty_remaining_values(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="WARRANTY-CODE-001",
                    status="used",
                    has_warranty=True,
                    warranty_days=30,
                    used_by_email="buyer@example.com",
                    used_at=get_now(),
                )
            )
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=8,
                    expires_at=get_now() + timedelta(days=12),
                    source="auto_redeem",
                    last_redeem_code="WARRANTY-CODE-001",
                )
            )
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=1,
                    expires_at=get_now() + timedelta(days=3),
                    source="manual",
                    last_redeem_code="OTHER-WARRANTY-ORDER",
                )
            )
            await session.commit()

            result = await self.service.get_all_codes(
                db_session=session,
                page=1,
                per_page=50,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["codes"]), 1)
        code = result["codes"][0]
        self.assertTrue(code["has_warranty"])
        self.assertEqual(code["warranty_days"], 30)
        self.assertEqual(code["warranty_remaining_days"], 12)
        self.assertGreater(code["warranty_remaining_seconds"], 11 * 86400)
        self.assertRegex(code["warranty_remaining_time"], r"^11天 23:")
        self.assertIsNotNone(code["warranty_expires_at"])
        self.assertEqual(code["warranty_remaining_claims"], 8)

    async def test_get_all_codes_filters_warranty_codes_by_multiple_conditions(self):
        now = get_now()
        async with self.Session() as session:
            session.add_all([
                RedemptionCode(
                    code="WARRANTY-MATCH-001",
                    status="used",
                    has_warranty=True,
                    warranty_days=30,
                    used_by_email="buyer@example.com",
                    used_at=now,
                    created_at=now - timedelta(days=2),
                ),
                RedemptionCode(
                    code="WARRANTY-SHORT-001",
                    status="used",
                    has_warranty=True,
                    warranty_days=7,
                    used_by_email="short@example.com",
                    used_at=now,
                    created_at=now - timedelta(days=2),
                ),
                RedemptionCode(
                    code="WARRANTY-LOW-CLAIMS-001",
                    status="used",
                    has_warranty=True,
                    warranty_days=30,
                    used_by_email="low@example.com",
                    used_at=now,
                    created_at=now - timedelta(days=2),
                ),
                RedemptionCode(
                    code="NORMAL-CODE-001",
                    status="unused",
                    has_warranty=False,
                    created_at=now - timedelta(days=2),
                ),
            ])
            session.add_all([
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=8,
                    expires_at=now + timedelta(days=12),
                    source="auto_redeem",
                    last_redeem_code="WARRANTY-MATCH-001",
                ),
                WarrantyEmailEntry(
                    email="short@example.com",
                    remaining_claims=8,
                    expires_at=now + timedelta(days=5),
                    source="auto_redeem",
                    last_redeem_code="WARRANTY-SHORT-001",
                ),
                WarrantyEmailEntry(
                    email="low@example.com",
                    remaining_claims=2,
                    expires_at=now + timedelta(days=12),
                    source="auto_redeem",
                    last_redeem_code="WARRANTY-LOW-CLAIMS-001",
                ),
            ])
            await session.commit()

            result = await self.service.get_all_codes(
                db_session=session,
                page=1,
                per_page=50,
                code_type="warranty",
                created_from=now - timedelta(days=3),
                created_to=now,
                warranty_days=30,
                remaining_days_min=10,
                remaining_days_max=15,
                remaining_claims_min=5,
                remaining_claims_max=10,
            )

        self.assertTrue(result["success"])
        self.assertEqual([code["code"] for code in result["codes"]], ["WARRANTY-MATCH-001"])

    async def test_get_all_codes_filters_unused_warranty_codes_by_configured_remaining_values(self):
        now = get_now()
        async with self.Session() as session:
            session.add_all([
                RedemptionCode(
                    code="UNUSED-WARRANTY-MATCH",
                    status="unused",
                    has_warranty=True,
                    warranty_days=13,
                    warranty_seconds=12 * 86400 + 3600,
                    warranty_claims=6,
                    created_at=now,
                ),
                RedemptionCode(
                    code="UNUSED-WARRANTY-OUTSIDE",
                    status="unused",
                    has_warranty=True,
                    warranty_days=3,
                    warranty_claims=1,
                    created_at=now,
                ),
            ])
            await session.commit()

            result = await self.service.get_all_codes(
                db_session=session,
                page=1,
                per_page=50,
                status="unused",
                code_type="warranty",
                remaining_days_min=10,
                remaining_days_max=15,
                remaining_claims_min=5,
                remaining_claims_max=10,
            )

        self.assertTrue(result["success"])
        self.assertEqual([code["code"] for code in result["codes"]], ["UNUSED-WARRANTY-MATCH"])
        self.assertEqual(result["codes"][0]["warranty_remaining_days"], 13)
        self.assertEqual(result["codes"][0]["warranty_remaining_seconds"], 12 * 86400 + 3600)
        self.assertEqual(result["codes"][0]["warranty_remaining_time"], "12天 01:00:00")
        self.assertIsNone(result["codes"][0]["warranty_expires_at"])
        self.assertEqual(result["codes"][0]["warranty_remaining_claims"], 6)

    async def test_get_all_codes_treats_usage_record_as_authoritative_status(self):
        now = get_now()
        async with self.Session() as session:
            session.add_all([
                RedemptionCode(
                    code="RECORDED-AS-UNUSED",
                    status="unused",
                    has_warranty=False,
                    created_at=now,
                ),
                RedemptionCode(
                    code="TRUE-UNUSED",
                    status="unused",
                    has_warranty=False,
                    created_at=now,
                ),
            ])
            session.add(
                RedemptionRecord(
                    email="buyer@example.com",
                    code="RECORDED-AS-UNUSED",
                    team_id=1,
                    account_id="acc-usage-record",
                    redeemed_at=now,
                )
            )
            await session.commit()

            all_result = await self.service.get_all_codes(
                db_session=session,
                page=1,
                per_page=50,
            )
            used_result = await self.service.get_all_codes(
                db_session=session,
                page=1,
                per_page=50,
                status="used",
            )
            unused_result = await self.service.get_all_codes(
                db_session=session,
                page=1,
                per_page=50,
                status="unused",
            )
            stats = await self.service.get_stats(session)

        self.assertTrue(all_result["success"])
        code_map = {code["code"]: code for code in all_result["codes"]}
        recorded_code = code_map["RECORDED-AS-UNUSED"]
        self.assertEqual(recorded_code["status"], "used")
        self.assertEqual(recorded_code["used_by_email"], "buyer@example.com")
        self.assertEqual(recorded_code["used_team_id"], 1)
        self.assertIsNotNone(recorded_code["used_at"])
        self.assertEqual([code["code"] for code in used_result["codes"]], ["RECORDED-AS-UNUSED"])
        self.assertEqual([code["code"] for code in unused_result["codes"]], ["TRUE-UNUSED"])
        self.assertEqual(stats["used"], 1)
        self.assertEqual(stats["unused"], 1)


if __name__ == "__main__":
    unittest.main()
