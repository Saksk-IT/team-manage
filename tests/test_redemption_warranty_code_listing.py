import os
import tempfile
import unittest
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, WarrantyEmailEntry
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
            await session.commit()

            result = await self.service.get_all_codes(
                db_session=session,
                page=1,
                per_page=50,
            )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["codes"]), 1)
        code = result["codes"][0]
        self.assertTrue(code["has_warranty"])
        self.assertEqual(code["warranty_days"], 30)
        self.assertEqual(code["warranty_remaining_days"], 12)
        self.assertEqual(code["warranty_remaining_claims"], 8)


if __name__ == "__main__":
    unittest.main()
