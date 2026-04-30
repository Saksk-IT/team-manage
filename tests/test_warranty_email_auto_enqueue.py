import os
import tempfile
import unittest
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team, WarrantyEmailEntry
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

    async def test_sync_warranty_email_entry_after_redeem_creates_default_entry_for_warranty_code(self):
        async with self.Session() as session:
            service = WarrantyService()
            await service.sync_warranty_email_entry_after_redeem(
                db_session=session,
                email="buyer@example.com",
                redeem_code="CODE-123",
                has_warranty_code=True,
            )
            await session.commit()

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")
            serialized_entry = service.serialize_warranty_email_entry(entry)

        self.assertIsNotNone(entry)
        self.assertEqual(entry.remaining_claims, 10)
        self.assertEqual(serialized_entry["remaining_days"], 30)
        self.assertEqual(entry.last_redeem_code, "CODE-123")
        self.assertEqual(entry.source, "auto_redeem")

    async def test_sync_warranty_email_entry_after_redeem_skips_non_warranty_code(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="CODE-123",
                    status="unused",
                    has_warranty=False,
                    warranty_days=30,
                )
            )
            await session.commit()

            service = WarrantyService()
            await service.sync_warranty_email_entry_after_redeem(
                db_session=session,
                email="buyer@example.com",
                redeem_code="CODE-123",
                has_warranty_code=False,
            )
            await session.commit()

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertIsNone(entry)

    async def test_sync_warranty_email_entry_after_redeem_uses_code_record_as_source_of_truth(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="CODE-123",
                    status="unused",
                    has_warranty=True,
                    warranty_days=31,
                    warranty_seconds=30 * 86400 + 3600,
                )
            )
            await session.commit()

            service = WarrantyService()
            await service.sync_warranty_email_entry_after_redeem(
                db_session=session,
                email="buyer@example.com",
                redeem_code="CODE-123",
                has_warranty_code=False,
            )
            await session.commit()

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")
            serialized_entry = service.serialize_warranty_email_entry(entry)

        self.assertIsNotNone(entry)
        self.assertEqual(entry.remaining_claims, 10)
        self.assertEqual(serialized_entry["remaining_days"], 31)
        self.assertGreaterEqual(serialized_entry["remaining_seconds"], 30 * 86400 + 3595)
        self.assertLessEqual(serialized_entry["remaining_seconds"], 30 * 86400 + 3600)

    async def test_sync_warranty_email_entry_after_redeem_keeps_manual_and_adds_auto_order(self):
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
                redeem_code="NEW-CODE",
                has_warranty_code=True,
            )
            await session.commit()

            entries = await service.get_warranty_email_entries_for_email(session, "buyer@example.com")

        entries_by_source = {entry.source: entry for entry in entries}
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries_by_source["manual"].remaining_claims, 3)
        self.assertEqual(entries_by_source["manual"].last_redeem_code, "OLD-CODE")
        self.assertEqual(entries_by_source["auto_redeem"].remaining_claims, 10)
        self.assertEqual(entries_by_source["auto_redeem"].last_redeem_code, "NEW-CODE")

    async def test_sync_warranty_email_entry_after_redeem_keeps_old_auto_and_adds_new_code_order(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=1,
                    expires_at=get_now() + timedelta(days=1),
                    source="auto_redeem",
                    last_redeem_code="OLD-CODE"
                )
            )
            await session.commit()

            service = WarrantyService()
            await service.sync_warranty_email_entry_after_redeem(
                db_session=session,
                email="buyer@example.com",
                redeem_code="NEW-CODE",
                has_warranty_code=True,
            )
            await session.commit()

            entries = await service.get_warranty_email_entries_for_email(session, "buyer@example.com")
            entries_by_code = {entry.last_redeem_code: entry for entry in entries}
            serialized_entry = service.serialize_warranty_email_entry(entries_by_code["NEW-CODE"])

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries_by_code["OLD-CODE"].remaining_claims, 1)
        self.assertEqual(entries_by_code["NEW-CODE"].remaining_claims, 10)
        self.assertEqual(serialized_entry["remaining_days"], 30)
        self.assertEqual(entries_by_code["NEW-CODE"].source, "auto_redeem")

    async def test_sync_warranty_email_entry_after_redeem_records_redeemed_team(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-team",
                team_name="Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.flush()

            service = WarrantyService()
            await service.sync_warranty_email_entry_after_redeem(
                db_session=session,
                email="buyer@example.com",
                redeem_code="CODE-123",
                has_warranty_code=True,
                team_id=team.id,
            )
            await session.commit()

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.last_warranty_team_id, team.id)


if __name__ == "__main__":
    unittest.main()
