import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import Team, TeamMemberSnapshot
from app.routes.admin import team_member_snapshots_page
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
                email=" MEMBER@example.com ",
                team_id=None,
                member_state=None,
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
                email=None,
                team_id=str(second_team.id),
                member_state="invited",
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


if __name__ == "__main__":
    unittest.main()
