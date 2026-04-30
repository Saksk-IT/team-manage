import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import EmailWhitelistEntry, Team, TeamCleanupRecord, TeamMemberSnapshot, WarrantyEmailEntry
from app.services.warranty_expiry_cleanup import warranty_expiry_cleanup_service
from app.utils.time_utils import get_now


class WarrantyExpiryCleanupServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_run_once_removes_expired_warranty_member_and_deactivates_whitelist(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-team",
                team_name="Team",
                status="active",
                current_members=2,
                max_members=5,
            )
            session.add(team)
            await session.flush()
            expired_entry = WarrantyEmailEntry(
                email="Buyer@Example.com",
                remaining_claims=2,
                expires_at=get_now() - timedelta(minutes=1),
                source="auto_redeem",
                last_redeem_code="CODE-OLD",
                last_warranty_team_id=team.id,
            )
            session.add_all([
                expired_entry,
                EmailWhitelistEntry(
                    email="buyer@example.com",
                    source="warranty_email",
                    is_active=True,
                    last_warranty_team_id=team.id,
                ),
                TeamMemberSnapshot(
                    team_id=team.id,
                    email="buyer@example.com",
                    member_state="joined",
                ),
            ])
            await session.commit()

        with (
            patch(
                "app.services.warranty_expiry_cleanup.settings_service.get_warranty_expiry_auto_cleanup_config",
                new=AsyncMock(return_value={"enabled": True}),
            ),
            patch(
                "app.services.warranty_expiry_cleanup.AsyncSessionLocal",
                self.Session,
            ),
            patch(
                "app.services.warranty_expiry_cleanup.team_service.remove_invite_or_member",
                new=AsyncMock(return_value={"success": True, "message": "成员已删除"}),
            ) as mocked_remove,
        ):
            result = await warranty_expiry_cleanup_service.run_once()

        async with self.Session() as session:
            entry = await session.scalar(select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == expired_entry.id))
            whitelist_entry = await session.scalar(
                select(EmailWhitelistEntry).where(EmailWhitelistEntry.email == "buyer@example.com")
            )
            snapshot = await session.scalar(
                select(TeamMemberSnapshot).where(TeamMemberSnapshot.email == "buyer@example.com")
            )
            cleanup_record = await session.scalar(
                select(TeamCleanupRecord).where(TeamCleanupRecord.team_id == team.id)
            )

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(mocked_remove.await_count, 1)
        remove_kwargs = mocked_remove.await_args.kwargs
        self.assertEqual(remove_kwargs["team_id"], team.id)
        self.assertEqual(remove_kwargs["email"], "buyer@example.com")
        self.assertIsNotNone(remove_kwargs["db_session"])
        self.assertEqual(entry.remaining_claims, 0)
        self.assertFalse(whitelist_entry.is_active)
        self.assertIn("质保订单到期", whitelist_entry.note)
        self.assertIsNone(snapshot)
        self.assertIsNotNone(cleanup_record)
        self.assertEqual(cleanup_record.cleanup_source, "warranty_expiry")
        self.assertIn("质保订单到期自动清理", cleanup_record.cleanup_reason or "")
        self.assertEqual(cleanup_record.cleanup_status, "success")
        self.assertEqual(cleanup_record.removed_member_count, 1)
        self.assertEqual(cleanup_record.revoked_invite_count, 0)
        self.assertEqual(cleanup_record.whitelist_deactivated_count, 1)
        self.assertIn("buyer@example.com", cleanup_record.removed_member_emails or "")
        self.assertIn("buyer@example.com", cleanup_record.whitelist_deactivated_emails or "")
        self.assertEqual(result["items"][0]["cleanup_record_id"], cleanup_record.id)
        self.assertEqual(result["items"][0]["member_action"], "member_removed")

    async def test_run_once_keeps_whitelist_when_same_email_has_active_order(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-team",
                team_name="Team",
                status="active",
                current_members=2,
                max_members=5,
            )
            session.add(team)
            await session.flush()
            expired_entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=1,
                expires_at=get_now() - timedelta(minutes=1),
                source="auto_redeem",
                last_redeem_code="CODE-OLD",
                last_warranty_team_id=team.id,
            )
            active_entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=1,
                expires_at=get_now() + timedelta(days=3),
                source="auto_redeem",
                last_redeem_code="CODE-NEW",
                last_warranty_team_id=team.id,
            )
            session.add_all([
                expired_entry,
                active_entry,
                EmailWhitelistEntry(
                    email="buyer@example.com",
                    source="warranty_email",
                    is_active=True,
                    last_warranty_team_id=team.id,
                ),
            ])
            await session.commit()

        with (
            patch(
                "app.services.warranty_expiry_cleanup.settings_service.get_warranty_expiry_auto_cleanup_config",
                new=AsyncMock(return_value={"enabled": True}),
            ),
            patch("app.services.warranty_expiry_cleanup.AsyncSessionLocal", self.Session),
            patch(
                "app.services.warranty_expiry_cleanup.team_service.remove_invite_or_member",
                new=AsyncMock(return_value={"success": True, "message": "成员已删除"}),
            ),
        ):
            result = await warranty_expiry_cleanup_service.run_once()

        async with self.Session() as session:
            expired_after = await session.scalar(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == expired_entry.id)
            )
            active_after = await session.scalar(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == active_entry.id)
            )
            whitelist_entry = await session.scalar(
                select(EmailWhitelistEntry).where(EmailWhitelistEntry.email == "buyer@example.com")
            )

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(expired_after.remaining_claims, 0)
        self.assertEqual(active_after.remaining_claims, 1)
        self.assertTrue(whitelist_entry.is_active)

    async def test_run_once_skips_member_removal_when_same_team_has_active_order(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-team",
                team_name="Team",
                status="active",
                current_members=2,
                max_members=5,
            )
            session.add(team)
            await session.flush()
            expired_entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=1,
                expires_at=get_now() - timedelta(minutes=1),
                source="auto_redeem",
                last_redeem_code="CODE-OLD",
                last_warranty_team_id=team.id,
            )
            active_entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=1,
                expires_at=get_now() + timedelta(days=3),
                source="auto_redeem",
                last_redeem_code="CODE-NEW",
                last_warranty_team_id=team.id,
            )
            session.add_all([
                expired_entry,
                active_entry,
                TeamMemberSnapshot(
                    team_id=team.id,
                    email="buyer@example.com",
                    member_state="joined",
                ),
            ])
            await session.commit()

        with (
            patch(
                "app.services.warranty_expiry_cleanup.settings_service.get_warranty_expiry_auto_cleanup_config",
                new=AsyncMock(return_value={"enabled": True}),
            ),
            patch("app.services.warranty_expiry_cleanup.AsyncSessionLocal", self.Session),
            patch(
                "app.services.warranty_expiry_cleanup.team_service.remove_invite_or_member",
                new=AsyncMock(return_value={"success": True, "message": "成员已删除"}),
            ) as mocked_remove,
        ):
            result = await warranty_expiry_cleanup_service.run_once()

        async with self.Session() as session:
            expired_after = await session.scalar(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == expired_entry.id)
            )
            active_after = await session.scalar(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == active_entry.id)
            )
            snapshot = await session.scalar(
                select(TeamMemberSnapshot).where(TeamMemberSnapshot.email == "buyer@example.com")
            )

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(expired_after.remaining_claims, 0)
        self.assertEqual(active_after.remaining_claims, 1)
        self.assertIsNotNone(snapshot)
        mocked_remove.assert_not_awaited()

        with (
            patch(
                "app.services.warranty_expiry_cleanup.settings_service.get_warranty_expiry_auto_cleanup_config",
                new=AsyncMock(return_value={"enabled": True}),
            ),
            patch("app.services.warranty_expiry_cleanup.AsyncSessionLocal", self.Session),
            patch(
                "app.services.warranty_expiry_cleanup.team_service.remove_invite_or_member",
                new=AsyncMock(return_value={"success": True, "message": "成员已删除"}),
            ) as mocked_second_remove,
        ):
            second_result = await warranty_expiry_cleanup_service.run_once()

        self.assertEqual(second_result["processed_count"], 0)
        mocked_second_remove.assert_not_awaited()

    async def test_run_once_uses_next_expiry_delay_when_no_order_expired_yet(self):
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
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=1,
                    expires_at=get_now() + timedelta(seconds=30),
                    source="auto_redeem",
                    last_redeem_code="CODE-SOON",
                    last_warranty_team_id=team.id,
                )
            )
            await session.commit()

        with (
            patch(
                "app.services.warranty_expiry_cleanup.settings_service.get_warranty_expiry_auto_cleanup_config",
                new=AsyncMock(return_value={"enabled": True}),
            ),
            patch("app.services.warranty_expiry_cleanup.AsyncSessionLocal", self.Session),
        ):
            result = await warranty_expiry_cleanup_service.run_once()

        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(result["next_delay_minutes"], 1)


if __name__ == "__main__":
    unittest.main()
