import asyncio
import os
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    InviteJob,
    RedemptionCode,
    RedemptionRecord,
    Team,
    TeamMemberSnapshot,
    WarrantyClaimRecord,
    WarrantyEmailEntry,
)
from app.services.invite_queue import (
    JOB_STATUS_PROCESSING,
    JOB_STATUS_QUEUED,
    JOB_STATUS_SUCCESS,
    InviteQueueService,
)
from app.services.team import TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY
from app.utils.time_utils import get_now


class InviteQueueServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_redeem_teams_and_codes(self, team_count=3, code_count=9):
        async with self.Session() as session:
            teams = [
                Team(
                    email=f"owner-{index}@example.com",
                    access_token_encrypted="dummy",
                    account_id=f"acc-{index}",
                    team_type=TEAM_TYPE_STANDARD,
                    team_name=f"Team {index}",
                    status="active",
                    current_members=1,
                    reserved_members=0,
                    max_members=4,
                )
                for index in range(1, team_count + 1)
            ]
            session.add_all(teams)
            session.add_all([
                RedemptionCode(code=f"CODE-{index:03d}", status="unused")
                for index in range(1, code_count + 1)
            ])
            await session.commit()

    async def test_concurrent_redeem_submission_reserves_without_overselling(self):
        await self._seed_redeem_teams_and_codes(team_count=3, code_count=9)
        service = InviteQueueService()

        async def submit(index):
            async with self.Session() as session:
                return await service.submit_redeem_job(
                    db_session=session,
                    email=f"buyer-{index}@example.com",
                    code=f"CODE-{index:03d}",
                )

        results = await asyncio.gather(*(submit(index) for index in range(1, 10)))
        self.assertTrue(all(result["success"] for result in results))
        self.assertTrue(all(result["queued"] for result in results))

        async with self.Session() as session:
            team_rows = (await session.execute(select(Team).order_by(Team.id.asc()))).scalars().all()
            job_team_ids = (await session.execute(select(InviteJob.team_id))).scalars().all()
            processing_count = await session.scalar(
                select(func.count(RedemptionCode.id)).where(RedemptionCode.status == "processing")
            )

        self.assertEqual(processing_count, 9)
        self.assertGreater(len(set(job_team_ids)), 1)
        for team in team_rows:
            self.assertLessEqual((team.current_members or 0) + (team.reserved_members or 0), team.max_members)
        self.assertEqual([team.reserved_members for team in team_rows], [3, 3, 3])

    async def test_duplicate_redeem_submission_reuses_active_job(self):
        await self._seed_redeem_teams_and_codes(team_count=1, code_count=1)
        service = InviteQueueService()

        async with self.Session() as session:
            first = await service.submit_redeem_job(session, "buyer@example.com", "CODE-001")
            second = await service.submit_redeem_job(session, "buyer@example.com", "CODE-001")
            job_count = await session.scalar(select(func.count(InviteJob.id)))

        self.assertTrue(first["success"])
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(job_count, 1)

    async def test_same_email_multiple_codes_reserve_different_teams(self):
        await self._seed_redeem_teams_and_codes(team_count=4, code_count=4)
        service = InviteQueueService()

        async with self.Session() as session:
            results = []
            for index in range(1, 5):
                results.append(
                    await service.submit_redeem_job(
                        session,
                        "buyer@example.com",
                        f"CODE-{index:03d}",
                    )
                )
            jobs = (
                await session.execute(
                    select(InviteJob).where(InviteJob.email == "buyer@example.com").order_by(InviteJob.id.asc())
                )
            ).scalars().all()

        self.assertTrue(all(result["success"] for result in results))
        self.assertEqual([job.team_id for job in jobs], [1, 2, 3, 4])

    async def test_redeem_submission_skips_team_already_used_by_email(self):
        await self._seed_redeem_teams_and_codes(team_count=2, code_count=2)
        service = InviteQueueService()

        async with self.Session() as session:
            session.add(
                RedemptionRecord(
                    email="buyer@example.com",
                    code="OLD-CODE",
                    team_id=1,
                    account_id="acc-1",
                )
            )
            await session.commit()

            result = await service.submit_redeem_job(session, "buyer@example.com", "CODE-001")
            job = await session.get(InviteJob, result["job_id"])

        self.assertTrue(result["success"])
        self.assertEqual(job.team_id, 2)

    async def test_redeem_processing_tries_next_team_when_email_already_member(self):
        await self._seed_redeem_teams_and_codes(team_count=2, code_count=1)
        service = InviteQueueService()

        async with self.Session() as session:
            submit_result = await service.submit_redeem_job(session, "buyer@example.com", "CODE-001")

        service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
        service.team_service.ensure_access_token = AsyncMock(return_value="token")
        service.team_service.chatgpt_service.send_invite = AsyncMock(side_effect=[
            {"success": False, "error": "User already in workspace"},
            {"success": True, "data": {"account_invites": [{"id": "invite-2"}]}},
        ])

        with patch("app.services.invite_queue.AsyncSessionLocal", self.Session):
            await service.process_job_now(submit_result["job_id"])

        async with self.Session() as session:
            job = await session.get(InviteJob, submit_result["job_id"])
            code = await session.scalar(select(RedemptionCode).where(RedemptionCode.code == "CODE-001"))
            records = (
                await session.execute(select(RedemptionRecord).where(RedemptionRecord.code == "CODE-001"))
            ).scalars().all()

        self.assertEqual(job.status, JOB_STATUS_SUCCESS)
        self.assertEqual(job.team_id, 2)
        self.assertEqual(code.used_team_id, 2)
        self.assertEqual([record.team_id for record in records], [2])
        self.assertEqual(service.team_service.chatgpt_service.send_invite.await_count, 2)

    async def test_redeem_processing_skips_local_member_snapshot_without_using_code(self):
        await self._seed_redeem_teams_and_codes(team_count=2, code_count=1)
        service = InviteQueueService()

        async with self.Session() as session:
            session.add(
                TeamMemberSnapshot(
                    team_id=1,
                    email="buyer@example.com",
                    member_state="joined",
                )
            )
            await session.commit()

            submit_result = await service.submit_redeem_job(session, "buyer@example.com", "CODE-001")
            job = await session.get(InviteJob, submit_result["job_id"])

        self.assertEqual(job.team_id, 2)

    async def test_process_redeem_job_success_releases_reservation_and_marks_code_used(self):
        await self._seed_redeem_teams_and_codes(team_count=1, code_count=1)
        service = InviteQueueService()

        async with self.Session() as session:
            submit_result = await service.submit_redeem_job(session, "buyer@example.com", "CODE-001")

        service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
        service.team_service.ensure_access_token = AsyncMock(return_value="token")
        service.team_service.chatgpt_service.send_invite = AsyncMock(return_value={
            "success": True,
            "data": {"account_invites": [{"id": "invite-1"}]},
        })

        with patch("app.services.invite_queue.AsyncSessionLocal", self.Session):
            await service.process_job_now(submit_result["job_id"])

        async with self.Session() as session:
            job = await session.get(InviteJob, submit_result["job_id"])
            team = await session.get(Team, 1)
            code = await session.scalar(select(RedemptionCode).where(RedemptionCode.code == "CODE-001"))
            record_count = await session.scalar(select(func.count(RedemptionRecord.id)))

        self.assertEqual(job.status, JOB_STATUS_SUCCESS)
        self.assertEqual(team.reserved_members, 0)
        self.assertEqual(team.current_members, 2)
        self.assertEqual(code.status, "used")
        self.assertEqual(record_count, 1)

    async def test_recover_stale_processing_job_releases_reservation_and_requeues(self):
        async with self.Session() as session:
            team = Team(
                email="owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-1",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Team 1",
                status="active",
                current_members=1,
                reserved_members=1,
                max_members=4,
            )
            session.add(team)
            session.add(RedemptionCode(code="CODE-STALE", status="processing"))
            await session.flush()
            session.add(
                InviteJob(
                    job_type="redeem",
                    status=JOB_STATUS_PROCESSING,
                    email="buyer@example.com",
                    code="CODE-STALE",
                    team_id=team.id,
                    idempotency_key="redeem:CODE-STALE",
                    attempt_count=1,
                    max_attempts=5,
                    reservation_released=False,
                    started_at=get_now() - timedelta(seconds=1200),
                    created_at=get_now() - timedelta(seconds=1200),
                    updated_at=get_now() - timedelta(seconds=1200),
                )
            )
            await session.commit()

        with patch("app.services.invite_queue.AsyncSessionLocal", self.Session):
            result = await InviteQueueService().recover_stale_processing_jobs()

        async with self.Session() as session:
            job = await session.scalar(select(InviteJob).where(InviteJob.code == "CODE-STALE"))
            team = await session.get(Team, 1)

        self.assertEqual(result["recovered"], 1)
        self.assertEqual(job.status, JOB_STATUS_QUEUED)
        self.assertIsNone(job.team_id)
        self.assertTrue(job.reservation_released)
        self.assertEqual(team.reserved_members, 0)

    async def test_concurrent_warranty_submission_reuses_active_email_job_and_reserves(self):
        service = InviteQueueService()
        service.warranty_service.validate_warranty_claim_input = AsyncMock(
            return_value={
                "success": True,
                "normalized_email": "buyer@example.com",
                "warranty_entry": SimpleNamespace(last_redeem_code="CODE-123"),
                "latest_team_info": {"id": 99, "status": "banned"},
            }
        )

        async with self.Session() as session:
            session.add(
                Team(
                    email="owner@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-1",
                    team_type=TEAM_TYPE_STANDARD,
                    team_name="Team 1",
                    status="active",
                    current_members=1,
                    reserved_members=0,
                    max_members=2,
                )
            )
            await session.commit()

            first = await service.submit_warranty_job(session, "buyer@example.com")
            second = await service.submit_warranty_job(session, "buyer@example.com")
            team = await session.get(Team, 1)
            job_count = await session.scalar(select(func.count(InviteJob.id)))

        self.assertTrue(first["success"])
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(job_count, 1)
        self.assertEqual(team.reserved_members, 1)

    async def test_warranty_processing_records_before_team_before_success_record(self):
        service = InviteQueueService()

        async with self.Session() as session:
            before_team = Team(
                email="before-owner@example.com",
                access_token_encrypted="dummy-before",
                account_id="acc-before",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Before Team",
                status="banned",
                current_members=2,
                reserved_members=0,
                max_members=5,
            )
            after_team = Team(
                email="after-owner@example.com",
                access_token_encrypted="dummy-after",
                account_id="acc-after",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="After Team",
                status="active",
                current_members=1,
                reserved_members=0,
                max_members=5,
            )
            session.add_all([before_team, after_team])
            await session.flush()
            session.add_all([
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-WARRANTY",
                ),
                RedemptionRecord(
                    email="buyer@example.com",
                    code="CODE-WARRANTY",
                    team_id=before_team.id,
                    account_id=before_team.account_id,
                    redeemed_at=get_now() - timedelta(minutes=10),
                    is_warranty_redemption=False,
                ),
            ])
            await session.commit()

            with patch.object(
                service.warranty_service.team_service,
                "refresh_team_state",
                AsyncMock(return_value={"success": True, "member_emails": []}),
            ):
                submit_result = await service.submit_warranty_job(session, "buyer@example.com")

        service.team_service.refresh_team_state = AsyncMock(return_value={"success": True, "member_emails": []})
        service.team_service.ensure_access_token = AsyncMock(return_value="token")
        service.team_service.chatgpt_service.send_invite = AsyncMock(return_value={
            "success": True,
            "data": {"account_invites": [{"id": "invite-1"}]},
        })

        with patch("app.services.invite_queue.AsyncSessionLocal", self.Session):
            await service.process_job_now(submit_result["job_id"])

        async with self.Session() as session:
            claim_record = await session.scalar(
                select(WarrantyClaimRecord).where(WarrantyClaimRecord.email == "buyer@example.com")
            )

        self.assertIsNotNone(claim_record)
        self.assertEqual(claim_record.before_team_id, before_team.id)
        self.assertEqual(claim_record.before_team_name, "Before Team")
        self.assertEqual(claim_record.after_team_id, after_team.id)
        self.assertEqual(claim_record.after_team_name, "After Team")


if __name__ == "__main__":
    unittest.main()
