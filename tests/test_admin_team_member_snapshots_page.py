import os
import tempfile
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import Team, TeamMemberSnapshot
from unittest.mock import AsyncMock, patch

from app.routes.admin import remove_team_member_snapshot_entry, team_member_snapshots_page
from app.services.team import TEAM_TYPE_STANDARD


class AdminTeamMemberSnapshotsPageTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin/team-member-snapshots", "headers": []})

    async def _seed_snapshots(self, session):
        first_team = Team(
            email="owner-1@example.com",
            access_token_encrypted="dummy-token-1",
            account_id="acc-1",
            team_type=TEAM_TYPE_STANDARD,
            team_name="First Snapshot Team",
            status="active",
            current_members=2,
            max_members=5,
        )
        second_team = Team(
            email="owner-2@example.com",
            access_token_encrypted="dummy-token-2",
            account_id="acc-2",
            team_type=TEAM_TYPE_STANDARD,
            team_name="Second Snapshot Team",
            status="full",
            current_members=5,
            max_members=5,
        )
        session.add_all([first_team, second_team])
        await session.flush()

        session.add_all([
            TeamMemberSnapshot(
                team_id=first_team.id,
                email="member@example.com",
                member_state="joined",
            ),
            TeamMemberSnapshot(
                team_id=second_team.id,
                email="member@example.com",
                member_state="invited",
            ),
            TeamMemberSnapshot(
                team_id=second_team.id,
                email="other@example.com",
                member_state="joined",
            ),
        ])
        await session.commit()
        return first_team, second_team

    async def test_page_lists_all_teams_for_exact_email(self):
        async with self.Session() as session:
            await self._seed_snapshots(session)

            response = await team_member_snapshots_page(
                request=self._build_request(),
                search=" MEMBER@example.com ",
                team_id=None,
                member_state=None,
                team_status=None,
                team_count_min=None,
                team_count_max=None,
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("成员快照", html)
        self.assertIn("member@example.com", html)
        self.assertIn("First Snapshot Team", html)
        self.assertIn("Second Snapshot Team", html)
        self.assertNotIn("other@example.com", html)

    async def test_page_filters_by_team_and_member_state(self):
        async with self.Session() as session:
            _, second_team = await self._seed_snapshots(session)

            response = await team_member_snapshots_page(
                request=self._build_request(),
                search=None,
                team_id=str(second_team.id),
                member_state="invited",
                team_status=None,
                team_count_min=None,
                team_count_max=None,
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("Second Snapshot Team", html)
        self.assertIn("member@example.com", html)
        self.assertIn("待加入", html)
        self.assertNotIn("other@example.com", html)
        self.assertNotIn("First Snapshot Team", html)

    async def test_page_supports_search_by_team_account_and_team_count_range(self):
        async with self.Session() as session:
            _, second_team = await self._seed_snapshots(session)

            response = await team_member_snapshots_page(
                request=self._build_request(),
                search="owner-2@example.com",
                team_id=None,
                member_state=None,
                team_status=None,
                team_count_min="2",
                team_count_max="2",
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("成员邮箱数", html)
        self.assertIn("跨 Team 成员邮箱", html)
        self.assertIn("所在 Team 个数", html)
        self.assertIn("owner-2@example.com", html)
        self.assertIn("member@example.com", html)
        self.assertIn(">2<", html)
        self.assertNotIn("other@example.com", html)
        self.assertIn("撤回邀请", html)
        self.assertIn("removeSnapshotMember(", html)

    async def test_page_filters_by_team_status(self):
        async with self.Session() as session:
            await self._seed_snapshots(session)

            response = await team_member_snapshots_page(
                request=self._build_request(),
                search=None,
                team_id=None,
                member_state=None,
                team_status="full",
                team_count_min=None,
                team_count_max=None,
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("Team 状态", html)
        self.assertIn("Second Snapshot Team", html)
        self.assertIn("已满", html)
        self.assertIn("member@example.com", html)
        self.assertIn("other@example.com", html)
        self.assertNotIn("First Snapshot Team", html)

    async def test_remove_snapshot_entry_uses_delete_for_joined_member(self):
        async with self.Session() as session:
            first_team, _ = await self._seed_snapshots(session)
            snapshot = await session.scalar(
                select(TeamMemberSnapshot).where(
                    TeamMemberSnapshot.team_id == first_team.id,
                    TeamMemberSnapshot.email == "member@example.com",
                )
            )

            with patch(
                "app.routes.admin.team_service.get_team_members",
                new=AsyncMock(return_value={
                    "success": True,
                    "members": [{
                        "user_id": "user-123",
                        "email": "member@example.com",
                        "status": "joined",
                    }],
                }),
            ) as mocked_get_members, patch(
                "app.routes.admin.team_service.delete_team_member",
                new=AsyncMock(return_value={"success": True, "message": "已踢出成员", "error": None}),
            ) as mocked_delete_member:
                response = await remove_team_member_snapshot_entry(
                    snapshot_id=snapshot.id,
                    db=session,
                    current_user={"username": "admin"},
                )

        payload = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        mocked_get_members.assert_awaited_once()
        mocked_delete_member.assert_awaited_once_with(
            team_id=first_team.id,
            user_id="user-123",
            db_session=session,
            source="admin_member",
        )
        self.assertIn("success", payload)

    async def test_remove_snapshot_entry_uses_revoke_for_invited_member(self):
        async with self.Session() as session:
            _, second_team = await self._seed_snapshots(session)
            snapshot = await session.scalar(
                select(TeamMemberSnapshot).where(
                    TeamMemberSnapshot.team_id == second_team.id,
                    TeamMemberSnapshot.email == "member@example.com",
                )
            )

            with patch(
                "app.routes.admin.team_service.get_team_members",
                new=AsyncMock(return_value={
                    "success": True,
                    "members": [{
                        "user_id": None,
                        "email": "member@example.com",
                        "status": "invited",
                    }],
                }),
            ) as mocked_get_members, patch(
                "app.routes.admin.team_service.revoke_team_invite",
                new=AsyncMock(return_value={"success": True, "message": "已撤回邀请", "error": None}),
            ) as mocked_revoke_invite:
                response = await remove_team_member_snapshot_entry(
                    snapshot_id=snapshot.id,
                    db=session,
                    current_user={"username": "admin"},
                )

        self.assertEqual(response.status_code, 200)
        mocked_get_members.assert_awaited_once()
        mocked_revoke_invite.assert_awaited_once_with(
            team_id=second_team.id,
            email="member@example.com",
            db_session=session,
        )


if __name__ == "__main__":
    unittest.main()
