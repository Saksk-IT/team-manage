import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import WarrantyEmailEntry, WarrantyEmailTemplateLock
from app.services.warranty import WarrantyService


class WarrantyEmailTemplateLockTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_email_first_query_randomly_locks_template_and_reuses_it(self):
        service = WarrantyService()
        match_templates = [
            {"id": "match-a", "content": "<p>A</p>"},
            {"id": "match-b", "content": "<p>B</p>"},
        ]
        miss_templates = [{"id": "miss-a", "content": "<p>未命中</p>"}]

        async with self.Session() as session:
            session.add(WarrantyEmailEntry(email="buyer@example.com", remaining_claims=1))
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="match-b") as mocked_choice:
                first_result = await service.check_warranty_email_membership(
                    session,
                    "Buyer@Example.com",
                    match_templates=match_templates,
                    miss_templates=miss_templates,
                )
                second_result = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    match_templates=match_templates,
                    miss_templates=miss_templates,
                )

            locks = (await session.execute(select(WarrantyEmailTemplateLock))).scalars().all()

        mocked_choice.assert_called_once_with(["match-a", "match-b"])
        self.assertTrue(first_result["matched"])
        self.assertEqual(first_result["template_key"], "match-b")
        self.assertEqual(second_result["template_key"], "match-b")
        self.assertTrue(second_result["template_matched"])
        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0].email, "buyer@example.com")
        self.assertTrue(locks[0].matched)
        self.assertEqual(locks[0].template_key, "match-b")

    async def test_unmatched_email_locks_miss_template(self):
        service = WarrantyService()

        async with self.Session() as session:
            with patch("app.services.warranty.secrets.choice", return_value="miss-b"):
                result = await service.check_warranty_email_membership(
                    session,
                    "none@example.com",
                    match_templates=[{"id": "match-a", "content": "<p>A</p>"}],
                    miss_templates=[
                        {"id": "miss-a", "content": "<p>A</p>"},
                        {"id": "miss-b", "content": "<p>B</p>"},
                    ],
                )
            lock = await session.scalar(select(WarrantyEmailTemplateLock))

        self.assertFalse(result["matched"])
        self.assertEqual(result["template_key"], "miss-b")
        self.assertFalse(result["template_matched"])
        self.assertEqual(lock.email, "none@example.com")
        self.assertFalse(lock.matched)
        self.assertEqual(lock.template_key, "miss-b")


if __name__ == "__main__":
    unittest.main()
