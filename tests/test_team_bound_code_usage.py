import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, Team
from app.services.team import TeamService


class TeamBoundCodeUsageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path}",
            future=True,
        )
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.service = TeamService()

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_get_all_teams_includes_bound_code_usage_summary(self):
        now = datetime(2026, 3, 22, 10, 0, 0)

        async with self.Session() as session:
            bound_team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-owner",
                team_name="Bound Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            latest_used_team = Team(
                email="latest-owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-latest",
                team_name="Latest Used Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add_all([bound_team, latest_used_team])
            await session.flush()

            code = RedemptionCode(
                code="CODE-001",
                status="used",
                bound_team_id=bound_team.id,
                used_by_email="latest@example.com",
                used_team_id=latest_used_team.id,
                used_at=now,
            )
            session.add(code)
            await session.flush()

            session.add_all([
                RedemptionRecord(
                    email="older@example.com",
                    code=code.code,
                    team_id=bound_team.id,
                    account_id=bound_team.account_id,
                    redeemed_at=now - timedelta(days=1),
                ),
                RedemptionRecord(
                    email="latest@example.com",
                    code=code.code,
                    team_id=latest_used_team.id,
                    account_id=latest_used_team.account_id,
                    redeemed_at=now,
                    is_warranty_redemption=True,
                ),
            ])
            await session.commit()

            result = await self.service.get_all_teams(session)

        self.assertTrue(result["success"])

        bound_team_data = next(team for team in result["teams"] if team["id"] == bound_team.id)
        self.assertEqual(bound_team_data["bound_code_count"], 1)

        bound_code = bound_team_data["bound_codes"][0]
        self.assertEqual(bound_code["code"], "CODE-001")
        self.assertEqual(bound_code["used_by_email"], "latest@example.com")
        self.assertEqual(bound_code["redemption_count"], 2)
        self.assertEqual(bound_code["latest_redemption"]["email"], "latest@example.com")
        self.assertEqual(bound_code["latest_redemption"]["team_name"], "Latest Used Team")
        self.assertEqual(
            [record["email"] for record in bound_code["redemption_records"]],
            ["latest@example.com", "older@example.com"],
        )


if __name__ == "__main__":
    unittest.main()
