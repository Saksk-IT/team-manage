import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, call

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    RedemptionCode,
    RedemptionRecord,
    Team,
    TeamMemberSnapshot,
    WarrantyClaimRecord,
    WarrantyEmailEntry,
)
from app.services.team import TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY
from app.services.warranty import WarrantyService
from app.utils.time_utils import get_now


class WarrantyClaimTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_team_data(self, session):
        ordinary_team = Team(
            email="ordinary-owner@example.com",
            access_token_encrypted="dummy",
            account_id="acc-ordinary",
            team_type=TEAM_TYPE_STANDARD,
            team_name="Ordinary Team",
            status="active",
            current_members=2,
            max_members=5
        )
        warranty_team = Team(
            email="warranty-owner@example.com",
            access_token_encrypted="dummy",
            account_id="acc-warranty",
            team_type=TEAM_TYPE_WARRANTY,
            team_name="Warranty Team",
            status="active",
            current_members=1,
            max_members=5
        )
        session.add_all([ordinary_team, warranty_team])
        await session.flush()
        return ordinary_team, warranty_team

    async def _add_latest_team_record(
        self,
        session,
        team,
        email: str,
        code: str,
        is_warranty_redemption: bool = False
    ):
        session.add(RedemptionCode(code=code, status="used"))
        session.add(
            RedemptionRecord(
                email=email,
                code=code,
                team_id=team.id,
                account_id=team.account_id,
                redeemed_at=get_now(),
                is_warranty_redemption=is_warranty_redemption
            )
        )

    async def test_validate_warranty_claim_input_rejects_missing_entry(self):
        async with self.Session() as session:
            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                email="missing@example.com"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该邮箱不在质保邮箱列表中")

    async def test_validate_warranty_claim_input_rejects_zero_claims(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=0,
                    expires_at=get_now() + timedelta(days=3),
                    source="manual"
                )
            )
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该邮箱暂无可用质保次数")

    async def test_validate_warranty_claim_input_rejects_expired_entry(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() - timedelta(days=1),
                    source="manual"
                )
            )
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该邮箱质保资格已过期")

    async def test_claim_warranty_success_decrements_claims_and_creates_record(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "banned"
            session.add_all([
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-123"
                )
            ])
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-123"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")
            record_count_result = await session.execute(
                select(func.count(RedemptionRecord.id)).where(
                    RedemptionRecord.code == "CODE-123",
                    RedemptionRecord.email == "buyer@example.com",
                    RedemptionRecord.team_id == warranty_team.id,
                    RedemptionRecord.is_warranty_redemption.is_(True)
                )
            )
            claim_record_result = await session.execute(
                select(WarrantyClaimRecord).where(WarrantyClaimRecord.email == "buyer@example.com")
            )
            claim_record = claim_record_result.scalar_one()

        self.assertTrue(result["success"])
        self.assertEqual(entry.remaining_claims, 1)
        self.assertEqual(entry.last_warranty_team_id, warranty_team.id)
        self.assertEqual(record_count_result.scalar(), 1)
        self.assertEqual(claim_record.claim_status, "success")
        self.assertEqual(claim_record.before_team_id, ordinary_team.id)
        self.assertEqual(claim_record.after_team_id, warranty_team.id)
        self.assertIsNone(claim_record.failure_reason)

    async def test_claim_warranty_failure_creates_failed_claim_record(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_team_data(session)
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-FAILED"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-FAILED"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )

            claim_record_result = await session.execute(
                select(WarrantyClaimRecord).where(WarrantyClaimRecord.email == "buyer@example.com")
            )
            claim_record = claim_record_result.scalar_one()

        self.assertFalse(result["success"])
        self.assertEqual(claim_record.claim_status, "failed")
        self.assertEqual(claim_record.before_team_id, ordinary_team.id)
        self.assertEqual(claim_record.before_team_status, "active")
        self.assertEqual(
            claim_record.failure_reason,
            "该邮箱最近加入的 Team 当前状态为「正常」，仅封禁后可提交质保"
        )
        self.assertIsNone(claim_record.after_team_id)

    async def test_claim_warranty_prefers_smallest_available_team_id(self):
        async with self.Session() as session:
            ordinary_team, smallest_warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "banned"

            larger_warranty_team = Team(
                email="warranty-owner-2@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty-2",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team 2",
                status="active",
                current_members=1,
                max_members=5
            )
            session.add(larger_warranty_team)
            await session.flush()

            smallest_warranty_team.created_at = get_now() + timedelta(minutes=1)
            larger_warranty_team.created_at = get_now() - timedelta(minutes=1)

            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-SMALL-ID"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-SMALL-ID"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["team_info"]["id"], smallest_warranty_team.id)
        service.team_service.add_team_member.assert_awaited_once_with(
            smallest_warranty_team.id,
            "buyer@example.com",
            session,
            source="user_warranty",
        )

    async def test_claim_warranty_does_not_fallback_to_other_available_team(self):
        async with self.Session() as session:
            ordinary_team, smallest_warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "banned"

            larger_warranty_team = Team(
                email="warranty-owner-2@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty-2",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team 2",
                status="active",
                current_members=1,
                max_members=5
            )
            session.add(larger_warranty_team)
            await session.flush()

            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-NO-FALLBACK"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-NO-FALLBACK"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(
                return_value={"success": False, "error": "发送邀请失败: upstream timeout"}
            )

            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )
            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "发送邀请失败: upstream timeout")
        self.assertEqual(entry.remaining_claims, 2)
        self.assertIsNone(entry.last_warranty_team_id)
        service.team_service.add_team_member.assert_awaited_once_with(
            smallest_warranty_team.id,
            "buyer@example.com",
            session,
            source="user_warranty",
        )

    async def test_claim_warranty_falls_back_to_next_team_for_empty_invite_list_error(self):
        async with self.Session() as session:
            ordinary_team, smallest_warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "banned"

            larger_warranty_team = Team(
                email="warranty-owner-2@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty-2",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team 2",
                status="active",
                current_members=1,
                max_members=5
            )
            session.add(larger_warranty_team)
            await session.flush()

            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-TRY-NEXT"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-TRY-NEXT"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(side_effect=[
                {
                    "success": False,
                    "error": "Team账号受限: 官方拦截下发(响应空列表)，请检查账单/风控状态",
                    "error_code": "invite_intercepted_empty_list",
                    "allow_try_next_team": True
                },
                {
                    "success": True,
                    "message": "邀请已发送"
                }
            ])

            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )
            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertTrue(result["success"])
        self.assertEqual(result["team_info"]["id"], larger_warranty_team.id)
        self.assertEqual(entry.remaining_claims, 1)
        self.assertEqual(entry.last_warranty_team_id, larger_warranty_team.id)
        service.team_service.add_team_member.assert_has_awaits(
            [
                call(smallest_warranty_team.id, "buyer@example.com", session, source="user_warranty"),
                call(larger_warranty_team.id, "buyer@example.com", session, source="user_warranty"),
            ]
        )

    async def test_claim_warranty_skips_warranty_unavailable_team(self):
        async with self.Session() as session:
            ordinary_team, unavailable_warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "banned"
            unavailable_warranty_team.warranty_unavailable = True
            unavailable_warranty_team.warranty_unavailable_reason = "官方拦截下发(响应空列表)"
            unavailable_warranty_team.warranty_unavailable_at = get_now()

            fallback_warranty_team = Team(
                email="warranty-owner-2@example.com",
                access_token_encrypted="dummy",
                account_id="acc-warranty-2",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Warranty Team 2",
                status="active",
                current_members=1,
                max_members=5
            )
            session.add(fallback_warranty_team)
            await session.flush()

            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-SKIP-UNAVAILABLE"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-SKIP-UNAVAILABLE"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["team_info"]["id"], fallback_warranty_team.id)
        service.team_service.add_team_member.assert_awaited_once_with(
            fallback_warranty_team.id,
            "buyer@example.com",
            session,
            source="user_warranty",
        )

    async def test_claim_warranty_rejects_when_latest_team_is_not_banned(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_team_data(session)
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-ACTIVE"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-ACTIVE"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service.team_service.add_team_member = AsyncMock()

            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "该邮箱最近加入的 Team 当前状态为「正常」，仅封禁后可提交质保")
        self.assertEqual(entry.remaining_claims, 2)
        service.team_service.add_team_member.assert_not_awaited()

    async def test_get_warranty_claim_status_returns_latest_team_status(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_team_data(session)
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-BANNED"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-BANNED"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})

            async def fake_sync(team_id, db_session, force_refresh=False, progress_callback=None, source=None):
                team = await db_session.get(Team, team_id)
                team.status = "banned"
                await db_session.commit()
                return {"success": True}

            service.team_service.refresh_team_state = AsyncMock(side_effect=fake_sync)

            result = await service.get_warranty_claim_status(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["can_claim"])
        self.assertEqual(result["latest_team"]["status"], "banned")
        service.team_service.refresh_team_state.assert_awaited_once_with(
            ordinary_team.id,
            session,
            source="user_warranty",
        )

    async def test_get_warranty_claim_status_requires_live_refresh_success(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_team_data(session)
            ordinary_team.status = "banned"
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-BANNED"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-BANNED"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service.team_service.refresh_team_state = AsyncMock(
                return_value={"success": False, "error": "上游接口超时"}
            )

            result = await service.get_warranty_claim_status(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "上游接口超时")
        service.team_service.refresh_team_state.assert_awaited_once_with(
            ordinary_team.id,
            session,
            source="user_warranty",
        )

    async def test_get_warranty_claim_status_treats_deactivated_workspace_as_banned(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_team_data(session)
            ordinary_team.status = "active"
            team_id = ordinary_team.id
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-BANNED"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-BANNED"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})

            async def fake_sync(team_id, db_session, force_refresh=False, progress_callback=None, source=None):
                team = await db_session.get(Team, team_id)
                team.status = "banned"
                return {
                    "success": False,
                    "error": "workspace 已停用",
                    "error_code": "deactivated_workspace"
                }

            service.team_service.refresh_team_state = AsyncMock(side_effect=fake_sync)

            result = await service.get_warranty_claim_status(
                db_session=session,
                email="buyer@example.com"
            )

        async with self.Session() as verify_session:
            persisted_team = await verify_session.get(Team, team_id)

        self.assertTrue(result["success"])
        self.assertTrue(result["can_claim"])
        self.assertEqual(result["latest_team"]["status"], "banned")
        self.assertEqual(persisted_team.status, "banned")

    async def test_get_warranty_claim_status_accepts_banned_team_even_when_sync_error_code_is_missing(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_team_data(session)
            ordinary_team.status = "active"
            team_id = ordinary_team.id
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-BANNED"
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-BANNED"
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})

            async def fake_sync(team_id, db_session, force_refresh=False, progress_callback=None, source=None):
                team = await db_session.get(Team, team_id)
                team.status = "banned"
                await db_session.commit()
                return {
                    "success": False,
                    "error": "{'code': 'deactivated_workspace'}",
                    "error_code": None
                }

            service.team_service.refresh_team_state = AsyncMock(side_effect=fake_sync)

            result = await service.get_warranty_claim_status(
                db_session=session,
                email="buyer@example.com"
            )

        async with self.Session() as verify_session:
            persisted_team = await verify_session.get(Team, team_id)

        self.assertTrue(result["success"])
        self.assertTrue(result["can_claim"])
        self.assertEqual(result["latest_team"]["status"], "banned")
        self.assertEqual(persisted_team.status, "banned")

    async def test_get_warranty_claim_status_prefers_latest_team_from_warranty_entry(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "active"
            warranty_team.status = "banned"
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-OLD",
                    last_warranty_team_id=warranty_team.id,
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-OLD",
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True})

            result = await service.get_warranty_claim_status(
                db_session=session,
                email="buyer@example.com",
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["can_claim"])
        self.assertEqual(result["latest_team"]["id"], warranty_team.id)
        self.assertEqual(result["latest_team"]["email"], warranty_team.email)
        service.team_service.refresh_team_state.assert_awaited_once_with(
            warranty_team.id,
            session,
            source="user_warranty",
        )

    async def test_get_warranty_claim_status_uses_team_member_snapshot_after_live_refresh(self):
        async with self.Session() as session:
            ordinary_team, _ = await self._seed_team_data(session)
            ordinary_team.status = "banned"
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual"
                )
            )
            session.add(
                TeamMemberSnapshot(
                    team_id=ordinary_team.id,
                    email="buyer@example.com",
                    member_state="joined",
                )
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True})

            result = await service.get_warranty_claim_status(
                db_session=session,
                email="buyer@example.com"
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["can_claim"])
        self.assertEqual(result["latest_team"]["status"], "banned")
        self.assertEqual(result["latest_team"]["code"], None)
        service.team_service.refresh_team_state.assert_awaited_once_with(
            ordinary_team.id,
            session,
            source="user_warranty",
        )

    async def test_claim_warranty_uses_team_member_snapshot_when_no_redemption_record_exists(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "banned"
            session.add_all([
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-123"
                ),
                RedemptionCode(code="CODE-123", status="used"),
                TeamMemberSnapshot(
                    team_id=ordinary_team.id,
                    email="buyer@example.com",
                    member_state="joined",
                )
            ])
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            service._find_existing_warranty_team_for_email = AsyncMock(return_value=None)
            service.team_service.add_team_member = AsyncMock(return_value={"success": True, "message": "邀请已发送"})

            result = await service.claim_warranty_invite(
                db_session=session,
                email="buyer@example.com"
            )

            entry = await service.get_warranty_email_entry(session, "buyer@example.com")

        self.assertTrue(result["success"])
        self.assertEqual(entry.remaining_claims, 1)
        self.assertEqual(result["team_info"]["id"], warranty_team.id)

    async def test_validate_warranty_claim_input_prefers_latest_team_from_warranty_entry(self):
        async with self.Session() as session:
            ordinary_team, warranty_team = await self._seed_team_data(session)
            ordinary_team.status = "active"
            warranty_team.status = "banned"
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-OLD",
                    last_warranty_team_id=warranty_team.id,
                )
            )
            await self._add_latest_team_record(
                session=session,
                team=ordinary_team,
                email="buyer@example.com",
                code="CODE-OLD",
            )
            await session.commit()

            service = WarrantyService()
            service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
            result = await service.validate_warranty_claim_input(
                db_session=session,
                email="buyer@example.com",
                require_latest_team_banned=True,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["latest_team_info"]["id"], warranty_team.id)


if __name__ == "__main__":
    unittest.main()
