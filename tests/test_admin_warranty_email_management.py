import json
import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, Team, WarrantyEmailEntry, WarrantyEmailTemplateLock
from app.routes.admin import (
    BulkWarrantyEmailDeleteRequest,
    BulkWarrantyEmailUpdateRequest,
    WarrantyEmailSaveRequest,
    bulk_delete_warranty_emails,
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
            linked_team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-linked",
                team_name="Linked Team",
                status="banned",
                current_members=2,
                max_members=5,
            )
            session.add(linked_team)
            await session.flush()
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-123",
                    last_warranty_team_id=linked_team.id,
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
        self.assertIn("质保邮箱列表", html)
        self.assertIn("buyer@example.com", html)
        self.assertIn("CODE-123", html)
        self.assertIn("Linked Team", html)
        self.assertIn("封禁", html)
        self.assertIn('class="status-badge status-banned"', html)
        self.assertIn('id="warrantyRemainingDays" class="form-control" min="0" value="30"', html)
        self.assertIn("质保邮箱列表</span>", html)
        self.assertIn("总质保邮箱", html)
        self.assertIn("有效邮箱", html)
        self.assertIn("剩余时间", html)
        self.assertIn("质保到期时间", html)
        self.assertIn("4天 23:", html)
        self.assertIn("warrantyEmailEditorModal", html)
        self.assertIn("openWarrantyEmailCreateModal", html)
        self.assertIn('id="warrantyRedeemCode"', html)
        self.assertIn('id="warrantyRemainingClaims" class="form-control" min="0" value="10" required', html)
        self.assertIn('id="warrantyRemainingHours"', html)
        self.assertIn('id="warrantyRemainingMinutes"', html)
        self.assertIn('id="warrantyRemainingSeconds"', html)
        self.assertIn('剩余时间会精确到秒', html)
        self.assertIn("批量删除", html)
        self.assertIn("function bulkDeleteWarrantyEmails()", html)
        self.assertIn("/admin/warranty-emails/bulk-delete", html)

        fill_script_start = html.index("function fillWarrantyEmailForm(entry)")
        fill_script_end = html.index("document.getElementById('warrantyEmailForm')")
        fill_script = html[fill_script_start:fill_script_end]
        self.assertIn("document.getElementById('warrantyRedeemCode').value", fill_script)
        self.assertIn("setWarrantyRemainingTimeInputs(", fill_script)
        self.assertIn("entry.remaining_seconds", fill_script)
        self.assertIn(
            "remainingClaimsInput.value = entry.remaining_claims === null || entry.remaining_claims === undefined ? '0' : String(entry.remaining_claims);",
            fill_script,
        )
        self.assertNotIn("remainingDaysInput.defaultValue", fill_script)
        self.assertNotIn("remainingClaimsInput.defaultValue", fill_script)

        submit_script_start = html.index("document.getElementById('warrantyEmailForm')")
        submit_script_end = html.index("function getSelectedWarrantyEmailIds()")
        submit_script = html[submit_script_start:submit_script_end]
        self.assertIn("redeem_code: redeemCode || null", submit_script)
        self.assertIn("remaining_seconds: remainingTime.seconds", submit_script)
        self.assertIn("parseWarrantyRemainingTimeSeconds", html)

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

    async def test_warranty_email_list_serializes_linked_team_status(self):
        async with self.Session() as session:
            linked_team = Team(
                email="linked-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-linked",
                team_name="Linked Status Team",
                status="full",
                current_members=5,
                max_members=5,
            )
            session.add(linked_team)
            await session.flush()
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-TEAM",
                    last_warranty_team_id=linked_team.id,
                )
            )
            await session.commit()

            entries = await warranty_service.list_warranty_email_entries(session)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["last_warranty_team_id"], linked_team.id)
        self.assertEqual(entries[0]["last_warranty_team_status"], "full")
        self.assertEqual(entries[0]["last_warranty_team_status_label"], "已满")
        self.assertEqual(entries[0]["last_warranty_team_name"], "Linked Status Team")

    async def test_warranty_email_list_shows_transfer_redeem_code_from_generation_record(self):
        async with self.Session() as session:
            now = get_now()
            entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=2,
                expires_at=now + timedelta(days=5),
                source="manual",
                last_redeem_code="CODE-123",
            )
            session.add(entry)
            await session.flush()
            session.add(
                WarrantyEmailTemplateLock(
                    email="buyer@example.com",
                    matched=True,
                    template_key="match-a",
                    generated_redeem_code="TMW-TRANSFER",
                    generated_redeem_code_remaining_days=5,
                    generated_redeem_code_entry_id=entry.id,
                    generated_redeem_code_generated_at=now,
                )
            )
            await session.commit()

            entries = await warranty_service.list_warranty_email_entries(session)
            response = await warranty_emails_page(
                request=self._build_request(),
                search="TMW-TRANSFER",
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertEqual(entries[0]["transfer_redeem_code"], "TMW-TRANSFER")
        self.assertEqual(entries[0]["transfer_redeem_code_remaining_days"], 5)
        self.assertIn("TMW-TRANSFER", html)
        self.assertIn("5 天", html)
        self.assertIn("列设置", html)
        self.assertIn("warrantyEmailColumnDropdown", html)

    async def test_warranty_emails_page_searches_only_list_order_code(self):
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
                ]
            )
            await session.commit()

            response = await warranty_emails_page(
                request=self._build_request(),
                search="LATEST-999",
                db=session,
                current_user={"username": "admin"}
            )

        html = response.body.decode("utf-8")
        self.assertIn("buyer@example.com", html)
        self.assertNotIn("other@example.com", html)

    async def test_warranty_email_list_expands_multiple_warranty_codes(self):
        async with self.Session() as session:
            first_team = Team(
                email="owner-one@example.com",
                access_token_encrypted="dummy",
                account_id="acc-one",
                team_name="Team One",
                status="banned",
                current_members=2,
                max_members=5,
            )
            second_team = Team(
                email="owner-two@example.com",
                access_token_encrypted="dummy",
                account_id="acc-two",
                team_name="Team Two",
                status="active",
                current_members=2,
                max_members=5,
            )
            session.add_all([first_team, second_team])
            await session.flush()
            now = get_now()
            session.add_all([
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=3,
                    expires_at=now + timedelta(days=30),
                    source="auto_redeem",
                    last_redeem_code="CODE-A"
                ),
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=1,
                    expires_at=now + timedelta(days=30),
                    source="auto_redeem",
                    last_redeem_code="CODE-B"
                ),
                RedemptionCode(
                    code="CODE-A",
                    status="used",
                    has_warranty=True,
                    warranty_days=30,
                    warranty_claims=3,
                    used_by_email="buyer@example.com",
                    used_team_id=first_team.id,
                    used_at=now - timedelta(days=2),
                ),
                RedemptionCode(
                    code="CODE-B",
                    status="used",
                    has_warranty=True,
                    warranty_days=30,
                    warranty_claims=1,
                    used_by_email="buyer@example.com",
                    used_team_id=second_team.id,
                    used_at=now - timedelta(days=1),
                ),
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-A",
                    team_id=first_team.id,
                    account_id=first_team.account_id,
                    redeemed_at=now - timedelta(days=2),
                    is_warranty_redemption=False,
                ),
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-B",
                    team_id=second_team.id,
                    account_id=second_team.account_id,
                    redeemed_at=now - timedelta(days=1),
                    is_warranty_redemption=False,
                ),
            ])
            await session.commit()

            entries = await warranty_service.list_warranty_email_entries(session)
            response = await warranty_emails_page(
                request=self._build_request(),
                search=None,
                db=session,
                current_user={"username": "admin"}
            )

        entries_by_code = {entry["last_redeem_code"]: entry for entry in entries}
        html = response.body.decode("utf-8")
        self.assertEqual(set(entries_by_code.keys()), {"CODE-A", "CODE-B"})
        self.assertEqual(entries_by_code["CODE-A"]["remaining_claims"], 3)
        self.assertEqual(entries_by_code["CODE-B"]["remaining_claims"], 1)
        self.assertIn("CODE-A", html)
        self.assertIn("CODE-B", html)

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

    async def test_warranty_emails_page_paginates_with_default_100_per_page(self):
        async with self.Session() as session:
            now = get_now()
            session.add_all([
                WarrantyEmailEntry(
                    email=f"user{i:03d}@example.com",
                    remaining_claims=3,
                    expires_at=now + timedelta(days=5),
                    source="manual",
                    updated_at=now + timedelta(seconds=i),
                )
                for i in range(105)
            ])
            await session.commit()

            first_page_response = await warranty_emails_page(
                request=self._build_request(),
                search=None,
                db=session,
                current_user={"username": "admin"}
            )
            second_page_response = await warranty_emails_page(
                request=self._build_request(),
                search=None,
                page="2",
                db=session,
                current_user={"username": "admin"}
            )

        first_page_html = first_page_response.body.decode("utf-8")
        second_page_html = second_page_response.body.decode("utf-8")
        checkbox_marker = 'class="warranty-email-checkbox"'

        self.assertEqual(first_page_html.count(checkbox_marker), 100)
        self.assertEqual(second_page_html.count(checkbox_marker), 5)
        self.assertIn("user104@example.com", first_page_html)
        self.assertNotIn("user000@example.com", first_page_html)
        self.assertIn("user000@example.com", second_page_html)
        self.assertIn('option value="100" selected', first_page_html)

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

            with patch("app.routes.admin.warranty_expiry_cleanup_service.wake") as mocked_wake:
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
        mocked_wake.assert_called_once_with()
        for entry in entries:
            self.assertEqual(entry.remaining_claims, 5)
            remaining_days = warranty_service._get_warranty_entry_remaining_days(entry)
            self.assertEqual(remaining_days, 7)

    async def test_bulk_delete_warranty_emails_deletes_selected_entries(self):
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
            entry_keep = WarrantyEmailEntry(
                email="keep@example.com",
                remaining_claims=3,
                expires_at=get_now() + timedelta(days=4),
                source="manual",
            )
            session.add_all([entry_one, entry_two, entry_keep])
            await session.commit()
            await session.refresh(entry_one)
            await session.refresh(entry_two)
            await session.refresh(entry_keep)

            response = await bulk_delete_warranty_emails(
                payload=BulkWarrantyEmailDeleteRequest(
                    entry_ids=[entry_one.id, entry_two.id, entry_one.id],
                ),
                db=session,
                current_user={"username": "admin"},
            )

            payload = json.loads(response.body.decode("utf-8"))
            deleted_one = await session.get(WarrantyEmailEntry, entry_one.id)
            deleted_two = await session.get(WarrantyEmailEntry, entry_two.id)
            kept_entry = await session.get(WarrantyEmailEntry, entry_keep.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["deleted_count"], 2)
        self.assertIsNone(deleted_one)
        self.assertIsNone(deleted_two)
        self.assertIsNotNone(kept_entry)

    async def test_save_and_delete_warranty_email(self):
        async with self.Session() as session:
            with patch("app.routes.admin.warranty_expiry_cleanup_service.wake") as mocked_wake:
                save_response = await save_warranty_email(
                    payload=WarrantyEmailSaveRequest(
                        email="buyer@example.com",
                        remaining_days=5,
                        remaining_seconds=5 * 86400 + 3661,
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
        self.assertRegex(save_payload["entry"]["remaining_time"], r"^5天 01:0[01]:\d{2}$")
        self.assertGreaterEqual(save_payload["entry"]["remaining_seconds"], 5 * 86400 + 3658)
        self.assertLessEqual(save_payload["entry"]["remaining_seconds"], 5 * 86400 + 3661)
        self.assertEqual(delete_response.status_code, 200)
        mocked_wake.assert_called_once_with()

    async def test_save_warranty_email_order_updates_matching_redeem_code_only(self):
        async with self.Session() as session:
            first_team = Team(
                email="owner-one@example.com",
                access_token_encrypted="dummy",
                account_id="acc-one",
                team_name="Team One",
                status="banned",
                current_members=2,
                max_members=5,
            )
            second_team = Team(
                email="owner-two@example.com",
                access_token_encrypted="dummy",
                account_id="acc-two",
                team_name="Team Two",
                status="banned",
                current_members=2,
                max_members=5,
            )
            session.add_all([first_team, second_team])
            await session.flush()

            now = get_now()
            entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=10,
                expires_at=now + timedelta(days=30),
                source="auto_redeem",
                last_redeem_code="CODE-B",
            )
            code_a = RedemptionCode(
                code="CODE-A",
                status="used",
                has_warranty=True,
                warranty_days=30,
                warranty_claims=3,
                used_by_email="buyer@example.com",
                used_team_id=first_team.id,
                used_at=now - timedelta(days=5),
            )
            code_b = RedemptionCode(
                code="CODE-B",
                status="used",
                has_warranty=True,
                warranty_days=30,
                warranty_claims=2,
                used_by_email="buyer@example.com",
                used_team_id=second_team.id,
                used_at=now - timedelta(days=4),
            )
            session.add_all([
                entry,
                code_a,
                code_b,
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-A",
                    team_id=first_team.id,
                    account_id=first_team.account_id,
                    redeemed_at=now - timedelta(days=5),
                    is_warranty_redemption=False,
                ),
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-A",
                    team_id=second_team.id,
                    account_id=second_team.account_id,
                    redeemed_at=now - timedelta(days=1),
                    is_warranty_redemption=True,
                ),
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-B",
                    team_id=second_team.id,
                    account_id=second_team.account_id,
                    redeemed_at=now - timedelta(days=4),
                    is_warranty_redemption=False,
                ),
            ])
            await session.commit()
            await session.refresh(entry)

            response = await save_warranty_email(
                payload=WarrantyEmailSaveRequest(
                    entry_id=entry.id,
                    email="buyer@example.com",
                    remaining_days=8,
                    remaining_seconds=8 * 86400 + 3723,
                    remaining_claims=5,
                    redeem_code="CODE-A",
                ),
                db=session,
                current_user={"username": "admin"},
            )
            payload = json.loads(response.body.decode("utf-8"))
            entries = await warranty_service.list_warranty_email_entries(session)
            refreshed_code_a = await session.get(RedemptionCode, code_a.id)
            refreshed_code_b = await session.get(RedemptionCode, code_b.id)

        entries_by_code = {item["last_redeem_code"]: item for item in entries}
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["entry"]["last_redeem_code"], "CODE-A")
        self.assertEqual(refreshed_code_a.warranty_claims, 3)
        self.assertIsNone(refreshed_code_a.warranty_expires_at)
        self.assertEqual(refreshed_code_b.warranty_claims, 2)
        self.assertIsNone(refreshed_code_b.warranty_expires_at)
        self.assertEqual(entries_by_code["CODE-A"]["remaining_claims"], 5)
        self.assertEqual(entries_by_code["CODE-A"]["remaining_days"], 9)
        self.assertRegex(entries_by_code["CODE-A"]["remaining_time"], r"^8天 01:02:0[0-3]$")
        self.assertNotIn("CODE-B", entries_by_code)


if __name__ == "__main__":
    unittest.main()
