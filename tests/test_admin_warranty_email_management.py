import json
import os
import tempfile
import unittest
from datetime import timedelta

from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, WarrantyEmailEntry
from app.routes.admin import (
    BulkWarrantyEmailUpdateRequest,
    WarrantyEmailSaveRequest,
    bulk_update_warranty_emails,
    delete_warranty_email,
    save_warranty_email,
    warranty_emails_page,
)
from app.services.warranty import warranty_service
from app.utils.time_utils import get_now


class AdminWarrantyEmailManagementTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin/warranty-emails", "headers": []})

    async def test_warranty_emails_page_renders_entry(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-123"
                )
            )
            await session.commit()

            response = await warranty_emails_page(
                request=self._build_request(),
                search=None,
                db=session,
                current_user={"username": "admin"}
            )

        html = response.body.decode("utf-8")
        self.assertIn("质保 Team 白名单", html)
        self.assertIn("buyer@example.com", html)
        self.assertIn("CODE-123", html)
        self.assertIn('id="warrantyRemainingDays" class="form-control" min="0" value="30"', html)
        self.assertIn("支持新增、编辑、删除与筛选", html)
        self.assertIn("质保 Team 白名单</span>", html)
        self.assertIn('id="warrantyRemainingClaims" class="form-control" min="0" value="10" required', html)

        fill_script_start = html.index("function fillWarrantyEmailForm(entry)")
        fill_script_end = html.index("document.getElementById('warrantyEmailForm')")
        fill_script = html[fill_script_start:fill_script_end]
        self.assertIn(
            "remainingDaysInput.value = entry.remaining_days === null || entry.remaining_days === undefined ? '' : String(entry.remaining_days);",
            fill_script,
        )
        self.assertIn(
            "remainingClaimsInput.value = entry.remaining_claims === null || entry.remaining_claims === undefined ? '0' : String(entry.remaining_claims);",
            fill_script,
        )
        self.assertNotIn("remainingDaysInput.defaultValue", fill_script)
        self.assertNotIn("remainingClaimsInput.defaultValue", fill_script)

    async def test_warranty_emails_page_supports_search_by_redeem_code(self):
        async with self.Session() as session:
            session.add_all(
                [
                    WarrantyEmailEntry(
                        email="buyer@example.com",
                        remaining_claims=2,
                        expires_at=get_now() + timedelta(days=5),
                        source="manual",
                        last_redeem_code="CODE-123"
                    ),
                    WarrantyEmailEntry(
                        email="other@example.com",
                        remaining_claims=1,
                        expires_at=get_now() + timedelta(days=3),
                        source="manual",
                        last_redeem_code="OTHER-456"
                    ),
                ]
            )
            await session.commit()

            response = await warranty_emails_page(
                request=self._build_request(),
                search="CODE-123",
                db=session,
                current_user={"username": "admin"}
            )

        html = response.body.decode("utf-8")
        self.assertIn("buyer@example.com", html)
        self.assertNotIn("other@example.com", html)
        self.assertIn('placeholder="搜索邮箱或兑换码"', html)

    async def test_warranty_emails_page_supports_search_by_historical_redeem_code(self):
        async with self.Session() as session:
            session.add_all(
                [
                    WarrantyEmailEntry(
                        email="buyer@example.com",
                        remaining_claims=2,
                        expires_at=get_now() + timedelta(days=5),
                        source="manual",
                        last_redeem_code="LATEST-999"
                    ),
                    WarrantyEmailEntry(
                        email="other@example.com",
                        remaining_claims=1,
                        expires_at=get_now() + timedelta(days=3),
                        source="manual",
                        last_redeem_code="OTHER-456"
                    ),
                    RedemptionCode(
                        code="HISTORY-123",
                        status="used",
                        has_warranty=True,
                        used_by_email="buyer@example.com",
                        used_at=get_now(),
                    ),
                    RedemptionRecord(
                        email="buyer@example.com",
                        code="HISTORY-123",
                        team_id=1,
                        account_id="account-1",
                        redeemed_at=get_now(),
                    ),
                ]
            )
            await session.commit()

            response = await warranty_emails_page(
                request=self._build_request(),
                search="HISTORY-123",
                db=session,
                current_user={"username": "admin"}
            )

        html = response.body.decode("utf-8")
        self.assertIn("buyer@example.com", html)
        self.assertNotIn("other@example.com", html)

    async def test_warranty_emails_page_supports_status_source_and_remaining_filters(self):
        async with self.Session() as session:
            session.add_all(
                [
                    WarrantyEmailEntry(
                        email="active@example.com",
                        remaining_claims=3,
                        expires_at=get_now() + timedelta(days=5, hours=1),
                        source="manual",
                    ),
                    WarrantyEmailEntry(
                        email="expired@example.com",
                        remaining_claims=3,
                        expires_at=get_now() - timedelta(days=1),
                        source="manual",
                    ),
                    WarrantyEmailEntry(
                        email="auto@example.com",
                        remaining_claims=3,
                        expires_at=get_now() + timedelta(days=5, hours=1),
                        source="auto_redeem",
                    ),
                    WarrantyEmailEntry(
                        email="low-claims@example.com",
                        remaining_claims=1,
                        expires_at=get_now() + timedelta(days=5, hours=1),
                        source="manual",
                    ),
                ]
            )
            await session.commit()

            response = await warranty_emails_page(
                request=self._build_request(),
                search=None,
                status_filter="active",
                source_filter="manual",
                remaining_claims_min="2",
                remaining_claims_max="4",
                remaining_days_min="5",
                remaining_days_max="6",
                db=session,
                current_user={"username": "admin"}
            )

        html = response.body.decode("utf-8")
        self.assertIn("active@example.com", html)
        self.assertNotIn("expired@example.com", html)
        self.assertNotIn("auto@example.com", html)
        self.assertNotIn("low-claims@example.com", html)
        self.assertIn('name="status_filter"', html)
        self.assertIn('name="source_filter"', html)
        self.assertIn('name="remaining_claims_min"', html)
        self.assertIn('name="remaining_days_max"', html)

    async def test_bulk_update_warranty_email_remaining_days_and_claims(self):
        async with self.Session() as session:
            entry_one = WarrantyEmailEntry(
                email="one@example.com",
                remaining_claims=1,
                expires_at=get_now() + timedelta(days=2),
                source="manual",
            )
            entry_two = WarrantyEmailEntry(
                email="two@example.com",
                remaining_claims=2,
                expires_at=get_now() + timedelta(days=3),
                source="auto_redeem",
            )
            session.add_all([entry_one, entry_two])
            await session.commit()
            await session.refresh(entry_one)
            await session.refresh(entry_two)

            response = await bulk_update_warranty_emails(
                payload=BulkWarrantyEmailUpdateRequest(
                    entry_ids=[entry_one.id, entry_two.id],
                    update_remaining_days=True,
                    remaining_days=7,
                    update_remaining_claims=True,
                    remaining_claims=5,
                ),
                db=session,
                current_user={"username": "admin"}
            )

            payload = json.loads(response.body.decode("utf-8"))
            entries = [
                await session.get(WarrantyEmailEntry, entry_one.id),
                await session.get(WarrantyEmailEntry, entry_two.id),
            ]

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["updated_count"], 2)
        for entry in entries:
            self.assertEqual(entry.remaining_claims, 5)
            remaining_days = warranty_service._get_warranty_entry_remaining_days(entry)
            self.assertEqual(remaining_days, 7)

    async def test_save_and_delete_warranty_email(self):
        async with self.Session() as session:
            save_response = await save_warranty_email(
                payload=WarrantyEmailSaveRequest(
                    email="buyer@example.com",
                    remaining_days=5,
                    remaining_claims=2
                ),
                db=session,
                current_user={"username": "admin"}
            )

            save_payload = json.loads(save_response.body.decode("utf-8"))
            entry_id = save_payload["entry"]["id"]

            delete_response = await delete_warranty_email(
                entry_id=entry_id,
                db=session,
                current_user={"username": "admin"}
            )

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_payload["success"])
        self.assertEqual(delete_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
