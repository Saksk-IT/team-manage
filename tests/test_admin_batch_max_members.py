import json
import os
import tempfile
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team
from app.routes.admin import BulkTeamMaxMembersRequest, batch_update_team_max_members


class AdminBatchMaxMembersTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_batch_update_max_members_updates_selected_teams_and_status(self):
        async with self.Session() as session:
            session.add_all([
                Team(
                    email="one@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-one",
                    status="active",
                    current_members=4,
                    max_members=9,
                ),
                Team(
                    email="two@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-two",
                    status="active",
                    current_members=5,
                    max_members=9,
                ),
            ])
            await session.commit()

            response = await batch_update_team_max_members(
                action_data=BulkTeamMaxMembersRequest(ids=[1, 2], max_members=4),
                db=session,
                current_user={"username": "admin"},
            )

            teams = (
                await session.execute(select(Team).order_by(Team.id.asc()))
            ).scalars().all()

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["success_count"], 2)
        self.assertEqual([team.max_members for team in teams], [4, 4])
        self.assertEqual([team.status for team in teams], ["full", "full"])

    async def test_batch_update_max_members_reports_missing_team(self):
        async with self.Session() as session:
            response = await batch_update_team_max_members(
                action_data=BulkTeamMaxMembersRequest(ids=[404], max_members=8),
                db=session,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["success_count"], 0)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["failed_items"][0]["team_id"], 404)


if __name__ == "__main__":
    unittest.main()
