import os
import tempfile
import unittest
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team, TeamMemberSnapshot, WarrantyEmailEntry
from app.services.team import TEAM_TYPE_STANDARD, TeamService


class TeamMemberSnapshotSyncTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_sync_team_info_persists_member_snapshots_and_updates_warranty_entry(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-1",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Sync Team",
                status="active",
                current_members=0,
                max_members=5,
                device_code_auth_enabled=False,
                error_count=0,
            )
            session.add_all([
                team,
                WarrantyEmailEntry(
                    email="member@example.com",
                    remaining_claims=2,
                    source="manual",
                ),
            ])
            await session.commit()

            service = TeamService()
            service.ensure_access_token = AsyncMock(return_value="access-token")
            service.chatgpt_service.get_account_info = AsyncMock(return_value={
                "success": True,
                "accounts": [{
                    "account_id": "acc-1",
                    "name": "Sync Team",
                    "plan_type": "team",
                    "subscription_plan": "chatgptteamplan",
                    "expires_at": None,
                    "has_active_subscription": True,
                    "account_user_role": "account-owner",
                }],
            })
            service.chatgpt_service.get_members = AsyncMock(return_value={
                "success": True,
                "total": 1,
                "members": [{"email": "member@example.com"}],
            })
            service.chatgpt_service.get_invites = AsyncMock(return_value={
                "success": True,
                "total": 1,
                "items": [{"email_address": "invite@example.com"}],
            })
            service.chatgpt_service.get_account_settings = AsyncMock(return_value={
                "success": True,
                "data": {"beta_settings": {"codex_device_code_auth": False}},
            })

            result = await service.sync_team_info(team.id, session, force_refresh=True)
            await session.commit()

            snapshots_result = await session.execute(
                select(TeamMemberSnapshot).where(TeamMemberSnapshot.team_id == team.id).order_by(TeamMemberSnapshot.email.asc())
            )
            snapshots = snapshots_result.scalars().all()

            warranty_entry_result = await session.execute(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == "member@example.com")
            )
            warranty_entry = warranty_entry_result.scalar_one()

        self.assertTrue(result["success"])
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0].email, "invite@example.com")
        self.assertEqual(snapshots[0].member_state, "invited")
        self.assertEqual(snapshots[1].email, "member@example.com")
        self.assertEqual(snapshots[1].member_state, "joined")
        self.assertEqual(warranty_entry.last_warranty_team_id, team.id)

    async def test_member_snapshot_sync_preserves_multi_order_team_links(self):
        async with self.Session() as session:
            first_team = Team(
                email="owner-1@example.com",
                access_token_encrypted="dummy-1",
                account_id="acc-1",
                team_type=TEAM_TYPE_STANDARD,
                team_name="First Team",
                status="active",
                current_members=0,
                max_members=5,
            )
            second_team = Team(
                email="owner-2@example.com",
                access_token_encrypted="dummy-2",
                account_id="acc-2",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Second Team",
                status="active",
                current_members=0,
                max_members=5,
            )
            session.add_all([first_team, second_team])
            await session.flush()
            first_entry = WarrantyEmailEntry(
                email="member@example.com",
                remaining_claims=2,
                source="manual",
                last_redeem_code="CODE-A",
                last_warranty_team_id=first_team.id,
            )
            second_entry = WarrantyEmailEntry(
                email="member@example.com",
                remaining_claims=2,
                source="manual",
                last_redeem_code="CODE-B",
                last_warranty_team_id=second_team.id,
            )
            session.add_all([first_entry, second_entry])
            await session.commit()

            service = TeamService()
            await service._sync_team_member_snapshots(
                team=first_team,
                joined_member_emails={"member@example.com"},
                invited_member_emails=set(),
                db_session=session,
            )
            await session.commit()

        self.assertEqual(first_entry.last_warranty_team_id, first_team.id)
        self.assertEqual(second_entry.last_warranty_team_id, second_team.id)


if __name__ == "__main__":
    unittest.main()
