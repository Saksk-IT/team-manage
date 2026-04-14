import os
import tempfile
import unittest
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import WarrantyEmailEntry
from app.services.warranty import WarrantyService
from app.utils.time_utils import get_now


class WarrantyEmailAutoEnqueueTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_sync_warranty_email_entry_after_redeem_creates_default_disabled_entry(self):
        async with self.Session() as session:
            service = WarrantyService()
            await service.sync_warranty_email_entry_after_redeem(
                db_session=session,
                email="buyer@example.com",
                redeem_code="CODE-123"
            )
            await session.commit()

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.remaining_claims, 0)
        self.assertIsNone(entry.expires_at)
        self.assertEqual(entry.last_redeem_code, "CODE-123")
        self.assertEqual(entry.source, "auto_redeem")

    async def test_sync_warranty_email_entry_after_redeem_does_not_override_manual_limits(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=3,
                    expires_at=get_now() + timedelta(days=7),
                    source="manual",
                    last_redeem_code="OLD-CODE"
                )
            )
            await session.commit()

            service = WarrantyService()
            await service.sync_warranty_email_entry_after_redeem(
                db_session=session,
                email="buyer@example.com",
                redeem_code="NEW-CODE"
            )
            await session.commit()

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertEqual(entry.remaining_claims, 3)
        self.assertIsNotNone(entry.expires_at)
        self.assertEqual(entry.last_redeem_code, "NEW-CODE")
        self.assertEqual(entry.source, "manual")


if __name__ == "__main__":
    unittest.main()
