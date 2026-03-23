import os
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team
from app.services.team import TeamService, TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY


class TeamTypeFeatureTests(unittest.IsolatedAsyncioTestCase):
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

    def _mock_import_dependencies(self, email: str, account_id: str, team_name: str):
        self.service.jwt_parser.is_token_expired = Mock(return_value=False)
        self.service.jwt_parser.extract_email = Mock(return_value=email)
        self.service.chatgpt_service.get_account_info = AsyncMock(return_value={
            "success": True,
            "accounts": [{
                "account_id": account_id,
                "name": team_name,
                "plan_type": "team",
                "subscription_plan": "chatgptteamplan",
                "expires_at": None,
                "has_active_subscription": True,
                "account_user_role": "account-owner"
            }]
        })
        self.service.chatgpt_service.get_members = AsyncMock(return_value={
            "success": True,
            "total": 1,
            "members": []
        })
        self.service.chatgpt_service.get_invites = AsyncMock(return_value={
            "success": True,
            "total": 0,
            "items": []
        })
        self.service.chatgpt_service.get_account_settings = AsyncMock(return_value={
            "success": True,
            "data": {"beta_settings": {}}
        })

    async def test_standard_import_generates_codes_but_warranty_import_does_not(self):
        async with self.Session() as session:
            self._mock_import_dependencies("standard@example.com", "11111111-1111-1111-1111-111111111111", "Standard Team")
            standard_result = await self.service.import_team_single(
                access_token="eyJ.standard.payload",
                db_session=session,
                email="standard@example.com",
                account_id="11111111-1111-1111-1111-111111111111",
                team_type=TEAM_TYPE_STANDARD
            )

            self._mock_import_dependencies("warranty@example.com", "22222222-2222-2222-2222-222222222222", "Warranty Team")
            warranty_result = await self.service.import_team_single(
                access_token="eyJ.warranty.payload",
                db_session=session,
                email="warranty@example.com",
                account_id="22222222-2222-2222-2222-222222222222",
                team_type=TEAM_TYPE_WARRANTY
            )

            code_count_result = await session.execute(select(func.count(RedemptionCode.id)))
            code_count = code_count_result.scalar() or 0

        self.assertTrue(standard_result["success"])
        self.assertEqual(standard_result["generated_code_count"], 4)
        self.assertTrue(warranty_result["success"])
        self.assertEqual(warranty_result["generated_code_count"], 0)
        self.assertEqual(code_count, 4)

    async def test_standard_inventory_queries_exclude_warranty_teams(self):
        async with self.Session() as session:
            session.add_all([
                Team(
                    email="standard@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-standard",
                    team_type=TEAM_TYPE_STANDARD,
                    team_name="Standard Team",
                    status="active",
                    current_members=2,
                    max_members=5
                ),
                Team(
                    email="warranty@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-warranty",
                    team_type=TEAM_TYPE_WARRANTY,
                    team_name="Warranty Team",
                    status="active",
                    current_members=1,
                    max_members=5
                )
            ])
            await session.commit()

            available_standard = await self.service.get_available_teams(session)
            total_standard_seats = await self.service.get_total_available_seats(session)
            warranty_stats = await self.service.get_stats(session, team_type=TEAM_TYPE_WARRANTY)

        self.assertEqual(len(available_standard["teams"]), 1)
        self.assertEqual(available_standard["teams"][0]["team_type"], TEAM_TYPE_STANDARD)
        self.assertEqual(total_standard_seats, 3)
        self.assertEqual(warranty_stats["total"], 1)
        self.assertEqual(warranty_stats["remaining_seats"], 4)


if __name__ == "__main__":
    unittest.main()
