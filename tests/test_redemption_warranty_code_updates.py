import os
import tempfile
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode
from app.services.redemption import RedemptionService


class RedemptionWarrantyCodeUpdateTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_update_code_can_convert_unused_normal_code_to_warranty(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="UNUSED-CODE-001",
                    status="unused",
                    has_warranty=False,
                    warranty_days=30,
                )
            )
            await session.commit()

            result = await self.service.update_code(
                code="UNUSED-CODE-001",
                db_session=session,
                has_warranty=True,
                warranty_days=45,
            )

            refreshed_code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "UNUSED-CODE-001")
            )

        self.assertTrue(result["success"])
        self.assertTrue(refreshed_code.has_warranty)
        self.assertEqual(refreshed_code.warranty_days, 45)
        self.assertEqual(refreshed_code.warranty_seconds, 45 * 86400)

    async def test_update_code_rejects_used_code_conversion_to_warranty(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="USED-CODE-001",
                    status="used",
                    has_warranty=False,
                    warranty_days=30,
                )
            )
            await session.commit()

            result = await self.service.update_code(
                code="USED-CODE-001",
                db_session=session,
                has_warranty=True,
                warranty_days=45,
            )

            refreshed_code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "USED-CODE-001")
            )

        self.assertFalse(result["success"])
        self.assertIn("仅允许修改未使用的兑换码", result["error"])
        self.assertFalse(refreshed_code.has_warranty)
        self.assertEqual(refreshed_code.warranty_days, 30)

    async def test_bulk_update_unused_warranty_code_quota_only_updates_eligible_codes(self):
        async with self.Session() as session:
            session.add_all([
                RedemptionCode(
                    code="UNUSED-WARRANTY-001",
                    status="unused",
                    has_warranty=True,
                    warranty_days=30,
                    warranty_claims=10,
                ),
                RedemptionCode(
                    code="UNUSED-NORMAL-001",
                    status="unused",
                    has_warranty=False,
                    warranty_days=30,
                    warranty_claims=10,
                ),
                RedemptionCode(
                    code="USED-WARRANTY-001",
                    status="used",
                    has_warranty=True,
                    warranty_days=30,
                    warranty_claims=10,
                ),
            ])
            await session.commit()

            result = await self.service.bulk_update_unused_warranty_code_quota(
                codes=[
                    "UNUSED-WARRANTY-001",
                    "UNUSED-NORMAL-001",
                    "USED-WARRANTY-001",
                ],
                db_session=session,
                remaining_days=13,
                remaining_seconds=12 * 86400 + 3600,
                remaining_claims=3,
            )

            updated_code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "UNUSED-WARRANTY-001")
            )
            normal_code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "UNUSED-NORMAL-001")
            )
            used_code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "USED-WARRANTY-001")
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["skipped_count"], 2)
        self.assertEqual(updated_code.warranty_days, 13)
        self.assertEqual(updated_code.warranty_seconds, 12 * 86400 + 3600)
        self.assertEqual(updated_code.warranty_claims, 3)
        self.assertEqual(normal_code.warranty_days, 30)
        self.assertEqual(normal_code.warranty_claims, 10)
        self.assertEqual(used_code.warranty_days, 30)
        self.assertEqual(used_code.warranty_claims, 10)


if __name__ == "__main__":
    unittest.main()
