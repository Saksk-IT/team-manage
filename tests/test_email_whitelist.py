import json
import os
import tempfile
import unittest
from datetime import timedelta

from starlette.requests import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import EmailWhitelistEntry, RedemptionCode, RedemptionRecord, WarrantyEmailEntry
from app.routes.admin import (
    EmailWhitelistSaveRequest,
    delete_email_whitelist_entry,
    email_whitelist_page,
    save_email_whitelist_entry,
    sync_email_whitelist_from_warranty_emails,
)
from app.services.email_whitelist import email_whitelist_service
from app.utils.time_utils import get_now


class EmailWhitelistTests(unittest.IsolatedAsyncioTestCase):
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

    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/email-whitelist", "headers": []})

    async def test_sync_includes_only_effective_warranty_email_entries(self):
        async with self.Session() as session:
            session.add_all([
                WarrantyEmailEntry(
                    email="active@example.com",
                    remaining_claims=1,
                    expires_at=get_now() + timedelta(days=3),
                    source="auto_redeem",
                ),
                WarrantyEmailEntry(
                    email="expired@example.com",
                    remaining_claims=1,
                    expires_at=get_now() - timedelta(days=1),
                    source="auto_redeem",
                ),
                WarrantyEmailEntry(
                    email="no-claims@example.com",
                    remaining_claims=0,
                    expires_at=get_now() + timedelta(days=3),
                    source="manual",
                ),
            ])
            await session.commit()

            allowed_emails = await email_whitelist_service.get_allowed_emails(session)
            await session.commit()

            entries_result = await session.execute(select(EmailWhitelistEntry))
            entries = {entry.email: entry for entry in entries_result.scalars().all()}

        self.assertEqual(allowed_emails, {"active@example.com"})
        self.assertIn("active@example.com", entries)
        self.assertEqual(entries["active@example.com"].source, "warranty_email")
        self.assertTrue(entries["active@example.com"].is_active)
        self.assertNotIn("expired@example.com", entries)
        self.assertNotIn("no-claims@example.com", entries)

    async def test_sync_backfills_legacy_manual_pull_warranty_email_entries(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="legacy-manual@example.com",
                    remaining_claims=0,
                    expires_at=None,
                    source="manual",
                    last_warranty_team_id=9,
                )
            )
            await session.commit()

            allowed_emails = await email_whitelist_service.get_allowed_emails(session)
            await session.commit()

            entry = await session.scalar(
                select(EmailWhitelistEntry).where(
                    EmailWhitelistEntry.email == "legacy-manual@example.com"
                )
            )

        self.assertIn("legacy-manual@example.com", allowed_emails)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.source, "manual_pull")
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.last_warranty_team_id, 9)

    async def test_sync_includes_console_team_bound_emails(self):
        async with self.Session() as session:
            session.add_all([
                RedemptionCode(
                    code="BOUND-CODE-001",
                    status="used",
                    bound_team_id=1,
                    used_team_id=1,
                    used_by_email="Bound@Example.com",
                ),
                RedemptionRecord(
                    email="record@example.com",
                    code="RECORD-CODE-001",
                    team_id=2,
                    account_id="acc-record",
                ),
            ])
            await session.commit()

            allowed_emails = await email_whitelist_service.get_allowed_emails(session)
            await session.commit()

            entries_result = await session.execute(select(EmailWhitelistEntry))
            entries = {entry.email: entry for entry in entries_result.scalars().all()}

        self.assertIn("bound@example.com", allowed_emails)
        self.assertIn("record@example.com", allowed_emails)
        self.assertEqual(entries["bound@example.com"].source, "console_team")
        self.assertEqual(entries["record@example.com"].source, "console_team")

    async def test_whitelist_page_renders_sidebar_and_filters(self):
        async with self.Session() as session:
            session.add(
                EmailWhitelistEntry(
                    email="manual@example.com",
                    source="manual",
                    is_active=True,
                    note="客服添加",
                )
            )
            await session.commit()

            response = await email_whitelist_page(
                request=self._build_request(),
                search="manual",
                status_filter="active",
                source_filter="manual",
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("邮箱白名单", html)
        self.assertIn("manual@example.com", html)
        self.assertIn("客服添加", html)
        self.assertIn('name="status_filter"', html)
        self.assertIn('name="source_filter"', html)
        self.assertIn('href="/admin/email-whitelist"', html)
        self.assertIn("一键同步质保邮箱列表", html)
        self.assertIn("function syncWhitelistFromWarrantyEmails()", html)
        self.assertIn("/admin/email-whitelist/sync-warranty-emails", html)

    async def test_save_and_delete_whitelist_entry(self):
        async with self.Session() as session:
            save_response = await save_email_whitelist_entry(
                payload=EmailWhitelistSaveRequest(
                    email="manual@example.com",
                    is_active=True,
                    note="手动保留",
                ),
                db=session,
                current_user={"username": "admin"},
            )
            save_payload = json.loads(save_response.body.decode("utf-8"))
            entry_id = save_payload["entry"]["id"]

            delete_response = await delete_email_whitelist_entry(
                entry_id=entry_id,
                db=session,
                current_user={"username": "admin"},
            )
            entry = await session.scalar(
                select(EmailWhitelistEntry).where(EmailWhitelistEntry.id == entry_id)
            )
            allowed_emails = await email_whitelist_service.get_allowed_emails(session)

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_payload["success"])
        self.assertEqual(save_payload["entry"]["source"], "manual")
        self.assertEqual(delete_response.status_code, 200)
        self.assertIsNotNone(entry)
        self.assertFalse(entry.is_active)
        self.assertNotIn("manual@example.com", allowed_emails)

    async def test_sync_whitelist_from_warranty_emails_keeps_only_effective_warranty_entries(self):
        async with self.Session() as session:
            session.add_all([
                WarrantyEmailEntry(
                    email="Active@Example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=3),
                    source="auto_redeem",
                    last_warranty_team_id=8,
                ),
                WarrantyEmailEntry(
                    email="expired@example.com",
                    remaining_claims=2,
                    expires_at=get_now() - timedelta(days=1),
                    source="auto_redeem",
                ),
                EmailWhitelistEntry(
                    email="manual@example.com",
                    source="manual",
                    is_active=True,
                    note="手动维护",
                ),
                EmailWhitelistEntry(
                    email="console@example.com",
                    source="console_team",
                    is_active=True,
                    note="控制台来源",
                ),
                RedemptionCode(
                    code="BOUND-CODE-001",
                    status="used",
                    bound_team_id=1,
                    used_team_id=1,
                    used_by_email="console@example.com",
                ),
            ])
            await session.commit()

            response = await sync_email_whitelist_from_warranty_emails(
                db=session,
                current_user={"username": "admin"},
            )
            payload = json.loads(response.body.decode("utf-8"))
            allowed_emails = await email_whitelist_service.get_allowed_emails(session)

            entries_result = await session.execute(select(EmailWhitelistEntry))
            entries = {entry.email: entry for entry in entries_result.scalars().all()}

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["target_count"], 1)
        self.assertEqual(allowed_emails, {"active@example.com"})
        self.assertEqual(entries["active@example.com"].source, "warranty_email")
        self.assertEqual(entries["active@example.com"].last_warranty_team_id, 8)
        self.assertTrue(entries["active@example.com"].is_active)
        self.assertFalse(entries["manual@example.com"].is_active)
        self.assertFalse(entries["console@example.com"].is_active)
        self.assertNotIn("expired@example.com", entries)


if __name__ == "__main__":
    unittest.main()
