import os
import tempfile
import unittest
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team, TeamCleanupRecord, TeamMemberSnapshot
from app.services.team import TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY, TeamService


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

    async def test_warranty_team_refresh_does_not_cleanup_members(self):
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
            service.chatgpt_service.get_members = AsyncMock(return_value={
                "success": True,
                "total": 2,
                "members": [
                    {"id": "owner-user", "email": "warranty-owner@example.com", "role": "account-owner"},
                    {"id": "stray-user", "email": "stray@example.com", "role": "standard-user"},
                ],
            })
            service.chatgpt_service.get_invites = AsyncMock(return_value={
                "success": True,
                "total": 1,
                "items": [
                    {"email_address": "stray-invite@example.com", "role": "standard-user"},
                ],
            })
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

        self.assertTrue(result["success"])
        self.assertEqual(result["cleanup_removed_member_count"], 0)
        self.assertEqual(result["cleanup_revoked_invite_count"], 0)
        self.assertEqual(service.chatgpt_service.get_members.await_count, 1)
        self.assertEqual(service.chatgpt_service.get_invites.await_count, 1)
        service.chatgpt_service.delete_member.assert_not_awaited()
        service.chatgpt_service.delete_invite.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
