import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode
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


if __name__ == "__main__":
    unittest.main()
