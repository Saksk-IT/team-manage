import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, Team, TeamCleanupRecord, TeamMemberSnapshot, WarrantyEmailEntry, WarrantyTeamWhitelistEntry
from app.services.team import TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY, TeamService
from app.utils.time_utils import get_now
from datetime import timedelta


class TeamStandardRefreshCleanupTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_standard_team_refresh_removes_non_bound_emails_and_updates_snapshots(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-standard",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Standard Team",
                status="active",
                current_members=0,
                max_members=5,
            )
            session.add(team)
            await session.flush()

            session.add_all([
                RedemptionCode(
                    code="BOUND-JOINED-001",
                    status="used",
                    bound_team_id=team.id,
                    used_team_id=team.id,
                    used_by_email="bound-joined@example.com",
                ),
                RedemptionCode(
                    code="BOUND-INVITE-001",
                    status="used",
                    bound_team_id=team.id,
                    used_team_id=team.id,
                    used_by_email="bound-invite@example.com",
                ),
            ])
            await session.commit()

            service = TeamService()
            service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.get_account_info = AsyncMock(return_value={
                "success": True,
                "accounts": [{
                    "account_id": "acc-standard",
                    "name": "Standard Team",
                    "plan_type": "team",
                    "subscription_plan": "chatgptteamplan",
                    "expires_at": None,
                    "has_active_subscription": True,
                    "account_user_role": "account-owner",
                }],
            })
            service.chatgpt_service.get_members = AsyncMock(side_effect=[
                {
                    "success": True,
                    "total": 3,
                    "members": [
                        {"id": "owner-user", "email": "owner@example.com", "role": "account-owner"},
                        {"id": "bound-user", "email": "bound-joined@example.com", "role": "standard-user"},
                        {"id": "stray-user", "email": "stray-joined@example.com", "role": "standard-user"},
                    ],
                },
                {
                    "success": True,
                    "total": 2,
                    "members": [
                        {"id": "owner-user", "email": "owner@example.com", "role": "account-owner"},
                        {"id": "bound-user", "email": "bound-joined@example.com", "role": "standard-user"},
                    ],
                },
            ])
            service.chatgpt_service.get_invites = AsyncMock(side_effect=[
                {
                    "success": True,
                    "total": 2,
                    "items": [
                        {"email_address": "bound-invite@example.com", "role": "standard-user"},
                        {"email_address": "stray-invite@example.com", "role": "standard-user"},
                    ],
                },
                {
                    "success": True,
                    "total": 1,
                    "items": [
                        {"email_address": "bound-invite@example.com", "role": "standard-user"},
                    ],
                },
            ])
            service.chatgpt_service.get_account_settings = AsyncMock(return_value={
                "success": True,
                "data": {"beta_settings": {"codex_device_code_auth": False}},
            })
            service.chatgpt_service.delete_member = AsyncMock(return_value={"success": True, "error": None})
            service.chatgpt_service.delete_invite = AsyncMock(return_value={"success": True, "error": None})

            result = await service.sync_team_info(
                team.id,
                session,
                force_refresh=True,
                enforce_bound_email_cleanup=True,
            )
            await session.commit()

            refreshed_team = await session.get(Team, team.id)
            snapshots_result = await session.execute(
                select(TeamMemberSnapshot)
                .where(TeamMemberSnapshot.team_id == team.id)
                .order_by(TeamMemberSnapshot.email.asc())
            )
            snapshots = snapshots_result.scalars().all()
            cleanup_record = await session.scalar(
                select(TeamCleanupRecord).where(TeamCleanupRecord.team_id == team.id)
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["cleanup_removed_member_count"], 1)
        self.assertEqual(result["cleanup_revoked_invite_count"], 1)
        self.assertEqual(result["cleanup_failed_count"], 0)
        self.assertIn("删除成员 1 个", result["message"])
        self.assertIn("撤回邀请 1 个", result["message"])
        self.assertEqual(refreshed_team.current_members, 3)
        self.assertEqual(refreshed_team.status, "active")
        service.chatgpt_service.delete_member.assert_awaited_once_with(
            "access-token",
            "acc-standard",
            "stray-user",
            session,
            identifier="owner@example.com",
        )
        service.chatgpt_service.delete_invite.assert_awaited_once_with(
            "access-token",
            "acc-standard",
            "stray-invite@example.com",
            session,
            identifier="owner@example.com",
        )
        self.assertEqual(
            [snapshot.email for snapshot in snapshots],
            [
                "bound-invite@example.com",
                "bound-joined@example.com",
                "owner@example.com",
            ],
        )
        self.assertEqual(
            [snapshot.member_state for snapshot in snapshots],
            ["invited", "joined", "joined"],
        )
        self.assertIsNotNone(cleanup_record)
        self.assertEqual(cleanup_record.cleanup_status, "success")
        self.assertEqual(cleanup_record.removed_member_count, 1)
        self.assertEqual(cleanup_record.revoked_invite_count, 1)
        self.assertIn("stray-joined@example.com", cleanup_record.removed_member_emails or "")
        self.assertIn("stray-invite@example.com", cleanup_record.revoked_invite_emails or "")

    async def test_warranty_team_refresh_removes_emails_outside_warranty_list(self):
        async with self.Session() as session:
            team = Team(
                email="warranty-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team",
                status="active",
                current_members=0,
                max_members=5,
            )
            session.add(team)
            await session.flush()
            session.add_all([
                WarrantyEmailEntry(
                    email="allowed@example.com",
                    remaining_claims=1,
                    expires_at=get_now() + timedelta(days=5),
                    source="auto_redeem",
                ),
                WarrantyEmailEntry(
                    email="manual@example.com",
                    remaining_claims=0,
                    source="manual",
                ),
                WarrantyEmailEntry(
                    email="allowed-invite@example.com",
                    remaining_claims=1,
                    expires_at=get_now() + timedelta(days=5),
                    source="auto_redeem",
                ),
                WarrantyTeamWhitelistEntry(
                    email="manual@example.com",
                    source="manual",
                    is_active=True,
                ),
            ])
            await session.commit()

            service = TeamService()
            service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.get_account_info = AsyncMock(return_value={
                "success": True,
                "accounts": [{
                    "account_id": "acc-warranty",
                    "name": "Warranty Team",
                    "plan_type": "team",
                    "subscription_plan": "chatgptteamplan",
                    "expires_at": None,
                    "has_active_subscription": True,
                    "account_user_role": "account-owner",
                }],
            })
            service.chatgpt_service.get_members = AsyncMock(side_effect=[
                {
                    "success": True,
                    "total": 4,
                    "members": [
                        {"id": "owner-user", "email": "warranty-owner@example.com", "role": "account-owner"},
                        {"id": "allowed-user", "email": "allowed@example.com", "role": "standard-user"},
                        {"id": "manual-user", "email": "manual@example.com", "role": "standard-user"},
                        {"id": "stray-user", "email": "stray@example.com", "role": "standard-user"},
                    ],
                },
                {
                    "success": True,
                    "total": 3,
                    "members": [
                        {"id": "owner-user", "email": "warranty-owner@example.com", "role": "account-owner"},
                        {"id": "allowed-user", "email": "allowed@example.com", "role": "standard-user"},
                        {"id": "manual-user", "email": "manual@example.com", "role": "standard-user"},
                    ],
                },
            ])
            service.chatgpt_service.get_invites = AsyncMock(side_effect=[
                {
                    "success": True,
                    "total": 2,
                    "items": [
                        {"email_address": "allowed-invite@example.com", "role": "standard-user"},
                        {"email_address": "stray-invite@example.com", "role": "standard-user"},
                    ],
                },
                {
                    "success": True,
                    "total": 1,
                    "items": [
                        {"email_address": "allowed-invite@example.com", "role": "standard-user"},
                    ],
                },
            ])
            service.chatgpt_service.get_account_settings = AsyncMock(return_value={
                "success": True,
                "data": {"beta_settings": {"codex_device_code_auth": False}},
            })
            service.chatgpt_service.delete_member = AsyncMock(return_value={"success": True, "error": None})
            service.chatgpt_service.delete_invite = AsyncMock(return_value={"success": True, "error": None})

            result = await service.sync_team_info(team.id, session)
            await session.commit()

            snapshots_result = await session.execute(
                select(TeamMemberSnapshot)
                .where(TeamMemberSnapshot.team_id == team.id)
                .order_by(TeamMemberSnapshot.email.asc())
            )
            snapshots = snapshots_result.scalars().all()
            cleanup_record = await session.scalar(
                select(TeamCleanupRecord).where(TeamCleanupRecord.team_id == team.id)
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["cleanup_removed_member_count"], 1)
        self.assertEqual(result["cleanup_revoked_invite_count"], 1)
        self.assertEqual(result["cleanup_failed_count"], 0)
        self.assertEqual(service.chatgpt_service.get_members.await_count, 2)
        self.assertEqual(service.chatgpt_service.get_invites.await_count, 2)
        service.chatgpt_service.delete_member.assert_awaited_once_with(
            "access-token",
            "acc-warranty",
            "stray-user",
            session,
            identifier="warranty-owner@example.com",
        )
        service.chatgpt_service.delete_invite.assert_awaited_once_with(
            "access-token",
            "acc-warranty",
            "stray-invite@example.com",
            session,
            identifier="warranty-owner@example.com",
        )
        self.assertEqual(
            [snapshot.email for snapshot in snapshots],
            [
                "allowed-invite@example.com",
                "allowed@example.com",
                "manual@example.com",
                "warranty-owner@example.com",
            ],
        )
        self.assertIsNotNone(cleanup_record)
        self.assertEqual(cleanup_record.removed_member_count, 1)
        self.assertEqual(cleanup_record.revoked_invite_count, 1)

    async def test_standard_team_cleanup_keeps_emails_from_redemption_records(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-standard",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Standard Team",
                status="active",
                current_members=0,
                max_members=5,
            )
            session.add(team)
            await session.flush()
            session.add(
                RedemptionRecord(
                    email="redeemed@example.com",
                    code="UNBOUND-CODE-001",
                    team_id=team.id,
                    account_id="acc-standard",
                )
            )
            await session.commit()

            service = TeamService()
            service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.get_account_info = AsyncMock(return_value={
                "success": True,
                "accounts": [{
                    "account_id": "acc-standard",
                    "name": "Standard Team",
                    "plan_type": "team",
                    "subscription_plan": "chatgptteamplan",
                    "expires_at": None,
                    "has_active_subscription": True,
                    "account_user_role": "account-owner",
                }],
            })
            service.chatgpt_service.get_members = AsyncMock(side_effect=[
                {
                    "success": True,
                    "total": 3,
                    "members": [
                        {"id": "owner-user", "email": "owner@example.com", "role": "account-owner"},
                        {"id": "redeemed-user", "email": "redeemed@example.com", "role": "standard-user"},
                        {"id": "stray-user", "email": "stray@example.com", "role": "standard-user"},
                    ],
                },
                {
                    "success": True,
                    "total": 2,
                    "members": [
                        {"id": "owner-user", "email": "owner@example.com", "role": "account-owner"},
                        {"id": "redeemed-user", "email": "redeemed@example.com", "role": "standard-user"},
                    ],
                },
            ])
            service.chatgpt_service.get_invites = AsyncMock(side_effect=[
                {"success": True, "total": 0, "items": []},
                {"success": True, "total": 0, "items": []},
            ])
            service.chatgpt_service.get_account_settings = AsyncMock(return_value={
                "success": True,
                "data": {"beta_settings": {"codex_device_code_auth": False}},
            })
            service.chatgpt_service.delete_member = AsyncMock(return_value={"success": True, "error": None})
            service.chatgpt_service.delete_invite = AsyncMock(return_value={"success": True, "error": None})

            result = await service.sync_team_info(
                team.id,
                session,
                enforce_bound_email_cleanup=True,
            )
            await session.commit()

            snapshots_result = await session.execute(
                select(TeamMemberSnapshot)
                .where(TeamMemberSnapshot.team_id == team.id)
                .order_by(TeamMemberSnapshot.email.asc())
            )
            snapshots = snapshots_result.scalars().all()

        self.assertTrue(result["success"])
        self.assertEqual(result["cleanup_removed_member_count"], 1)
        service.chatgpt_service.delete_member.assert_awaited_once_with(
            "access-token",
            "acc-standard",
            "stray-user",
            session,
            identifier="owner@example.com",
        )
        self.assertEqual(
            [snapshot.email for snapshot in snapshots],
            ["owner@example.com", "redeemed@example.com"],
        )

    async def test_warranty_team_refresh_backfills_snapshot_emails_before_cleanup(self):
        async with self.Session() as session:
            team = Team(
                email="warranty-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team",
                status="active",
                current_members=0,
                max_members=5,
            )
            session.add(team)
            await session.flush()
            session.add(
                TeamMemberSnapshot(
                    team_id=team.id,
                    email="legacy-manual@example.com",
                    member_state="joined",
                )
            )
            await session.commit()

            service = TeamService()
            service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.get_account_info = AsyncMock(return_value={
                "success": True,
                "accounts": [{
                    "account_id": "acc-warranty",
                    "name": "Warranty Team",
                    "plan_type": "team",
                    "subscription_plan": "chatgptteamplan",
                    "expires_at": None,
                    "has_active_subscription": True,
                    "account_user_role": "account-owner",
                }],
            })
            service.chatgpt_service.get_members = AsyncMock(side_effect=[
                {
                    "success": True,
                    "total": 3,
                    "members": [
                        {"id": "owner-user", "email": "warranty-owner@example.com", "role": "account-owner"},
                        {"id": "legacy-user", "email": "legacy-manual@example.com", "role": "standard-user"},
                        {"id": "stray-user", "email": "stray@example.com", "role": "standard-user"},
                    ],
                },
                {
                    "success": True,
                    "total": 2,
                    "members": [
                        {"id": "owner-user", "email": "warranty-owner@example.com", "role": "account-owner"},
                        {"id": "legacy-user", "email": "legacy-manual@example.com", "role": "standard-user"},
                    ],
                },
            ])
            service.chatgpt_service.get_invites = AsyncMock(side_effect=[
                {"success": True, "total": 0, "items": []},
                {"success": True, "total": 0, "items": []},
            ])
            service.chatgpt_service.get_account_settings = AsyncMock(return_value={
                "success": True,
                "data": {"beta_settings": {"codex_device_code_auth": False}},
            })
            service.chatgpt_service.delete_member = AsyncMock(return_value={"success": True, "error": None})
            service.chatgpt_service.delete_invite = AsyncMock(return_value={"success": True, "error": None})

            result = await service.sync_team_info(team.id, session)
            await session.commit()

            entry = await session.scalar(
                select(WarrantyTeamWhitelistEntry).where(WarrantyTeamWhitelistEntry.email == "legacy-manual@example.com")
            )

        self.assertTrue(result["success"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.source, "manual_pull")
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.last_warranty_team_id, team.id)
        service.chatgpt_service.delete_member.assert_awaited_once_with(
            "access-token",
            "acc-warranty",
            "stray-user",
            session,
            identifier="warranty-owner@example.com",
        )

    async def test_admin_added_warranty_member_enters_manual_whitelist(self):
        async with self.Session() as session:
            team = Team(
                email="warranty-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team",
                status="active",
                current_members=0,
                max_members=5,
            )
            session.add(team)
            await session.commit()

            service = TeamService()
            service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.send_invite = AsyncMock(return_value={
                "success": True,
                "data": {"account_invites": [{"id": "invite-1"}]},
            })
            service.sync_team_info = AsyncMock(return_value={
                "success": True,
                "member_emails": ["manual-added@example.com"],
            })

            with patch("app.services.team.asyncio.sleep", new=AsyncMock(return_value=None)):
                result = await service.add_team_member(
                    team_id=team.id,
                    email="Manual-Added@Example.com",
                    db_session=session,
                )

            entry = await session.scalar(
                select(WarrantyTeamWhitelistEntry).where(WarrantyTeamWhitelistEntry.email == "manual-added@example.com")
            )

        self.assertTrue(result["success"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.source, "manual_pull")
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.last_warranty_team_id, team.id)
        self.assertEqual(service.sync_team_info.await_count, 2)
        self.assertTrue(
            all(
                call.kwargs.get("enforce_bound_email_cleanup")
                for call in service.sync_team_info.await_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
