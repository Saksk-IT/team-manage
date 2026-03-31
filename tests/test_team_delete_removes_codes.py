import os
import tempfile
import unittest

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team
from app.services.team import TeamService, TEAM_TYPE_STANDARD


class TeamDeleteRemovesCodesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.service = TeamService()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_delete_team_removes_related_redemption_codes(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-delete-team",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Delete Me",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.flush()

            session.add_all([
                RedemptionCode(
                    code="BOUND-CODE-001",
                    status="unused",
                    bound_team_id=team.id
                ),
                RedemptionCode(
                    code="USED-CODE-001",
                    status="used",
                    used_team_id=team.id,
                    used_by_email="buyer@example.com"
                ),
                RedemptionCode(
                    code="BOTH-CODE-001",
                    status="used",
                    bound_team_id=team.id,
                    used_team_id=team.id,
                    used_by_email="buyer2@example.com"
                ),
            ])
            await session.commit()

            result = await self.service.delete_team(team.id, session)

            remaining_codes_result = await session.execute(select(func.count(RedemptionCode.id)))
            remaining_codes = remaining_codes_result.scalar() or 0
            deleted_team = await session.get(Team, team.id)

        self.assertTrue(result["success"])
        self.assertEqual(remaining_codes, 0)
        self.assertIsNone(deleted_team)


if __name__ == "__main__":
    unittest.main()
