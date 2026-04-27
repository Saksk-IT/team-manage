import os
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team
from app.services.team import (
    TeamService,
    TEAM_TYPE_STANDARD,
    TEAM_TYPE_WARRANTY,
    IMPORT_RETRY_ATTEMPTS,
)


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

    async def test_import_never_generates_codes_and_forces_standard_team(self):
        async with self.Session() as session:
            with patch(
                "app.services.team.settings_service.get_default_team_max_members",
                new=AsyncMock(return_value=8)
            ):
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
        self.assertEqual(standard_result["generated_code_count"], 0)
        self.assertEqual(standard_result["imported_teams"][0]["team_type"], TEAM_TYPE_STANDARD)
        self.assertEqual(standard_result["imported_teams"][0]["max_members"], 8)
        self.assertTrue(warranty_result["success"])
        self.assertEqual(warranty_result["generated_code_count"], 0)
        self.assertEqual(warranty_result["imported_teams"][0]["team_type"], TEAM_TYPE_STANDARD)
        self.assertEqual(warranty_result["imported_teams"][0]["max_members"], 8)
        self.assertEqual(code_count, 0)

    async def test_import_ignores_warranty_code_generation_options(self):
        async with self.Session() as session:
            with patch(
                "app.services.team.settings_service.get_default_team_max_members",
                new=AsyncMock(return_value=8)
            ):
                self._mock_import_dependencies(
                    "warranty-codes@example.com",
                    "12121212-1212-1212-1212-121212121212",
                    "Warranty Codes Team",
                )
                result = await self.service.import_team_single(
                    access_token="eyJ.warranty.codes.payload",
                    db_session=session,
                    email="warranty-codes@example.com",
                    account_id="12121212-1212-1212-1212-121212121212",
                    team_type=TEAM_TYPE_STANDARD,
                    generate_warranty_codes=True,
                    warranty_days=45,
                )

            codes_result = await session.execute(select(RedemptionCode))
            generated_codes = codes_result.scalars().all()
            team = await session.get(Team, result["team_id"])
            list_result = await self.service.get_all_teams(session)

        self.assertTrue(result["success"])
        self.assertEqual(result["generated_code_count"], 0)
        self.assertEqual(result["imported_teams"][0]["team_type"], TEAM_TYPE_STANDARD)
        self.assertEqual(result["imported_teams"][0]["bound_code_type"], TEAM_TYPE_STANDARD)
        self.assertIsNone(result["imported_teams"][0]["generated_code_warranty_days"])
        self.assertIsNone(team.bound_code_warranty_days)
        self.assertEqual(list_result["teams"][0]["bound_code_warranty_days"], None)
        self.assertEqual(generated_codes, [])

    async def test_import_rejects_specified_account_when_account_info_fetch_fails(self):
        self.service.jwt_parser.is_token_expired = Mock(return_value=False)
        self.service.jwt_parser.extract_email = Mock(return_value="owner@example.com")
        self.service.chatgpt_service.get_account_info = AsyncMock(return_value={
            "success": False,
            "accounts": [],
            "error": "invalid_workspace_selected",
        })
        self.service.chatgpt_service.get_members = AsyncMock()
        self.service.chatgpt_service.get_invites = AsyncMock()
        self.service.chatgpt_service.get_account_settings = AsyncMock()

        async with self.Session() as session:
            result = await self.service.import_team_single(
                access_token="eyJ.owner.payload",
                db_session=session,
                email="owner@example.com",
                account_id="33333333-3333-3333-3333-333333333333",
                team_type=TEAM_TYPE_STANDARD,
            )

            team_count_result = await session.execute(select(func.count(Team.id)))
            team_count = team_count_result.scalar() or 0

        self.assertFalse(result["success"])
        self.assertIn("获取账户信息失败", result["error"])
        self.assertEqual(team_count, 0)
        self.service.chatgpt_service.get_members.assert_not_called()
        self.service.chatgpt_service.get_invites.assert_not_called()

    async def test_import_recovers_from_invalid_workspace_selected_with_session_token(self):
        self.service.jwt_parser.is_token_expired = Mock(return_value=False)
        self.service.jwt_parser.extract_email = Mock(return_value="workspace@example.com")
        self.service.chatgpt_service.get_account_info = AsyncMock(side_effect=[
            {
                "success": False,
                "accounts": [],
                "error": '{"error":{"code":"invalid_workspace_selected"}}',
            },
            {
                "success": True,
                "accounts": [{
                    "account_id": "77777777-7777-7777-7777-777777777777",
                    "name": "Workspace Team",
                    "plan_type": "team",
                    "subscription_plan": "chatgptteamplan",
                    "expires_at": None,
                    "has_active_subscription": True,
                    "account_user_role": "account-owner"
                }]
            }
        ])
        self.service.chatgpt_service.refresh_access_token_with_session_token = AsyncMock(return_value={
            "success": True,
            "access_token": "eyJ.workspace.refreshed",
            "session_token": "session-token-new",
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
        self.service.chatgpt_service.clear_session = AsyncMock()

        async with self.Session() as session:
            result = await self.service.import_team_single(
                access_token="eyJ.workspace.original",
                db_session=session,
                email="workspace@example.com",
                account_id="77777777-7777-7777-7777-777777777777",
                session_token="session-token-old",
                team_type=TEAM_TYPE_STANDARD,
            )

        self.assertTrue(result["success"])
        self.service.chatgpt_service.clear_session.assert_awaited_once_with("workspace@example.com")
        self.service.chatgpt_service.refresh_access_token_with_session_token.assert_awaited_once_with(
            "session-token-old",
            unittest.mock.ANY,
            account_id="77777777-7777-7777-7777-777777777777",
            identifier="workspace@example.com",
        )
        self.assertEqual(self.service.chatgpt_service.get_account_info.await_count, 2)

    async def test_import_passes_account_id_when_fetching_account_info(self):
        self._mock_import_dependencies(
            "header@example.com",
            "88888888-8888-8888-8888-888888888888",
            "Header Team",
        )

        async with self.Session() as session:
            result = await self.service.import_team_single(
                access_token="eyJ.header.payload",
                db_session=session,
                email="header@example.com",
                account_id="88888888-8888-8888-8888-888888888888",
                team_type=TEAM_TYPE_STANDARD,
            )

        self.assertTrue(result["success"])
        self.service.chatgpt_service.get_account_info.assert_awaited_once_with(
            "eyJ.header.payload",
            unittest.mock.ANY,
            identifier="header@example.com",
            account_id="88888888-8888-8888-8888-888888888888",
        )

    async def test_import_uses_email_identifier_for_members_and_invites(self):
        self._mock_import_dependencies(
            "identifier@example.com",
            "44444444-4444-4444-4444-444444444444",
            "Identifier Team",
        )

        async with self.Session() as session:
            await self.service.import_team_single(
                access_token="eyJ.identifier.payload",
                db_session=session,
                email="identifier@example.com",
                account_id="44444444-4444-4444-4444-444444444444",
                team_type=TEAM_TYPE_STANDARD,
            )

        self.service.chatgpt_service.get_members.assert_awaited_once_with(
            "eyJ.identifier.payload",
            "44444444-4444-4444-4444-444444444444",
            unittest.mock.ANY,
            identifier="identifier@example.com",
        )
        self.service.chatgpt_service.get_invites.assert_awaited_once_with(
            "eyJ.identifier.payload",
            "44444444-4444-4444-4444-444444444444",
            unittest.mock.ANY,
            identifier="identifier@example.com",
        )

    async def test_import_retries_when_initial_member_count_is_zero(self):
        self.service.jwt_parser.is_token_expired = Mock(return_value=False)
        self.service.jwt_parser.extract_email = Mock(return_value="retry@example.com")
        self.service.chatgpt_service.get_account_info = AsyncMock(return_value={
            "success": True,
            "accounts": [{
                "account_id": "55555555-5555-5555-5555-555555555555",
                "name": "Retry Team",
                "plan_type": "team",
                "subscription_plan": "chatgptteamplan",
                "expires_at": None,
                "has_active_subscription": True,
                "account_user_role": "account-owner"
            }]
        })
        self.service.chatgpt_service.get_members = AsyncMock(side_effect=[
            {"success": True, "total": 0, "members": []},
            {"success": True, "total": 1, "members": []},
        ])
        self.service.chatgpt_service.get_invites = AsyncMock(return_value={
            "success": True,
            "total": 0,
            "items": []
        })
        self.service.chatgpt_service.get_account_settings = AsyncMock(return_value={
            "success": True,
            "data": {"beta_settings": {}}
        })
        self.service.chatgpt_service.clear_session = AsyncMock()

        with patch("app.services.team.asyncio.sleep", new=AsyncMock()):
            async with self.Session() as session:
                result = await self.service.import_team_single(
                    access_token="eyJ.retry.payload",
                    db_session=session,
                    email="retry@example.com",
                    account_id="55555555-5555-5555-5555-555555555555",
                    team_type=TEAM_TYPE_STANDARD,
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["imported_teams"][0]["current_members"], 1)
        self.assertEqual(self.service.chatgpt_service.get_members.await_count, 2)
        self.service.chatgpt_service.clear_session.assert_awaited_once_with("retry@example.com")

    async def test_import_fails_after_retries_when_initial_member_count_remains_zero(self):
        self.service.jwt_parser.is_token_expired = Mock(return_value=False)
        self.service.jwt_parser.extract_email = Mock(return_value="zero@example.com")
        self.service.chatgpt_service.get_account_info = AsyncMock(return_value={
            "success": True,
            "accounts": [{
                "account_id": "66666666-6666-6666-6666-666666666666",
                "name": "Zero Team",
                "plan_type": "team",
                "subscription_plan": "chatgptteamplan",
                "expires_at": None,
                "has_active_subscription": True,
                "account_user_role": "account-owner"
            }]
        })
        self.service.chatgpt_service.get_members = AsyncMock(return_value={
            "success": True,
            "total": 0,
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
        self.service.chatgpt_service.clear_session = AsyncMock()

        with patch("app.services.team.asyncio.sleep", new=AsyncMock()):
            async with self.Session() as session:
                result = await self.service.import_team_single(
                    access_token="eyJ.zero.payload",
                    db_session=session,
                    email="zero@example.com",
                    account_id="66666666-6666-6666-6666-666666666666",
                    team_type=TEAM_TYPE_STANDARD,
                )

                team_count_result = await session.execute(select(func.count(Team.id)))
                team_count = team_count_result.scalar() or 0

        self.assertFalse(result["success"])
        self.assertIn("初始成员数异常", result["error"])
        self.assertEqual(team_count, 0)
        self.assertEqual(self.service.chatgpt_service.get_members.await_count, IMPORT_RETRY_ATTEMPTS)
        self.assertEqual(self.service.chatgpt_service.clear_session.await_count, IMPORT_RETRY_ATTEMPTS - 1)

    async def test_inventory_queries_use_unified_team_pool(self):
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
            unified_stats = await self.service.get_stats(session)

        self.assertEqual(len(available_standard["teams"]), 2)
        self.assertEqual([team["id"] for team in available_standard["teams"]], [1, 2])
        self.assertEqual(total_standard_seats, 7)
        self.assertEqual(unified_stats["total"], 2)
        self.assertEqual(unified_stats["total_seats"], 8)
        self.assertEqual(unified_stats["remaining_seats"], 7)

    async def test_transfer_to_warranty_is_rejected_for_compatibility(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-standard-transfer",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Transfer Me",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.flush()

            session.add_all([
                RedemptionCode(
                    code="UNUSED-CODE-001",
                    status="unused",
                    bound_team_id=team.id,
                ),
                RedemptionCode(
                    code="USED-CODE-001",
                    status="used",
                    bound_team_id=team.id,
                    used_by_email="user@example.com",
                ),
            ])
            await session.commit()

            result = await self.service.transfer_team_type(
                team_id=team.id,
                target_team_type=TEAM_TYPE_WARRANTY,
                db_session=session,
            )

            refreshed_team = await session.get(Team, team.id)
            unused_code = await session.execute(
                select(RedemptionCode).where(RedemptionCode.code == "UNUSED-CODE-001")
            )
            used_code = await session.execute(
                select(RedemptionCode).where(RedemptionCode.code == "USED-CODE-001")
            )
            unused_code_obj = unused_code.scalar_one_or_none()
            used_code_obj = used_code.scalar_one_or_none()

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "目标 Team 类型无效")
        self.assertEqual(refreshed_team.team_type, TEAM_TYPE_STANDARD)
        self.assertIsNotNone(unused_code_obj)
        self.assertIsNotNone(used_code_obj)
        self.assertEqual(used_code_obj.bound_team_id, team.id)

    async def test_transfer_legacy_warranty_team_to_standard_does_not_generate_codes(self):
        async with self.Session() as session:
            team = Team(
                email="warranty-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty-transfer",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Transfer",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.commit()

            result = await self.service.transfer_team_type(
                team_id=team.id,
                target_team_type=TEAM_TYPE_STANDARD,
                db_session=session,
            )

            refreshed_team = await session.get(Team, team.id)
            codes_result = await session.execute(
                select(RedemptionCode).where(RedemptionCode.bound_team_id == team.id)
            )
            generated_codes = codes_result.scalars().all()

        self.assertTrue(result["success"])
        self.assertEqual(result["generated_code_count"], 0)
        self.assertEqual(result["generated_codes"], [])
        self.assertEqual(refreshed_team.team_type, TEAM_TYPE_STANDARD)
        self.assertEqual(len(generated_codes), 0)


if __name__ == "__main__":
    unittest.main()
