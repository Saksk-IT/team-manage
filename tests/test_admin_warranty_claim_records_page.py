import os
import tempfile
import unittest
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, Team, WarrantyClaimRecord
from app.routes.admin import warranty_claim_records_page
from app.services.team import TEAM_TYPE_WARRANTY
from app.utils.time_utils import get_now


class AdminWarrantyClaimRecordsPageTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin/warranty-claim-records", "headers": []})

    async def test_warranty_claim_records_page_renders_record_details(self):
        async with self.Session() as session:
            before_team = Team(
                email="before-owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-before",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Before Warranty Team",
                status="banned",
                current_members=5,
                max_members=5,
            )
            after_team = Team(
                email="after-owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-after",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="After Warranty Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add_all([before_team, after_team])
            await session.flush()

            session.add(
                WarrantyClaimRecord(
                    email="buyer@example.com",
                    before_team_id=before_team.id,
                    before_team_name=before_team.team_name,
                    before_team_email=before_team.email,
                    before_team_account_id=before_team.account_id,
                    before_team_status="banned",
                    before_team_recorded_at=get_now() - timedelta(hours=1),
                    claim_status="success",
                    after_team_id=after_team.id,
                    after_team_name=after_team.team_name,
                    after_team_email=after_team.email,
                    after_team_account_id=after_team.account_id,
                    after_team_recorded_at=get_now(),
                    submitted_at=get_now() - timedelta(minutes=5),
                    completed_at=get_now() - timedelta(minutes=4),
                )
            )
            await session.commit()

            response = await warranty_claim_records_page(
                request=self._build_request(),
                search=None,
                claim_status=None,
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("质保提交记录", html)
        self.assertIn("buyer@example.com", html)
        self.assertIn("Before Warranty Team", html)
        self.assertIn("After Warranty Team", html)
        self.assertIn("质保成功", html)
        self.assertIn("搜索邮箱、Team、Account ID、失败原因", html)

    async def test_warranty_claim_records_page_repairs_legacy_before_team_display(self):
        async with self.Session() as session:
            before_team = Team(
                email="before-legacy-owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-before-legacy",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="Before Legacy Team",
                status="banned",
                current_members=5,
                max_members=5,
            )
            after_team = Team(
                email="after-legacy-owner@example.com",
                access_token_encrypted="dummy-token",
                account_id="acc-after-legacy",
                team_type=TEAM_TYPE_WARRANTY,
                team_name="After Legacy Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add_all([before_team, after_team])
            await session.flush()

            submitted_at = get_now()
            session.add_all([
                RedemptionCode(code="CODE-LEGACY", status="used"),
                RedemptionRecord(
                    email="legacy-buyer@example.com",
                    code="CODE-LEGACY",
                    team_id=before_team.id,
                    account_id=before_team.account_id,
                    redeemed_at=submitted_at - timedelta(hours=2),
                    is_warranty_redemption=False,
                ),
                WarrantyClaimRecord(
                    email="legacy-buyer@example.com",
                    before_team_id=after_team.id,
                    before_team_name=after_team.team_name,
                    before_team_email=after_team.email,
                    before_team_account_id=after_team.account_id,
                    before_team_status="active",
                    before_team_recorded_at=submitted_at,
                    claim_status="success",
                    after_team_id=after_team.id,
                    after_team_name=after_team.team_name,
                    after_team_email=after_team.email,
                    after_team_account_id=after_team.account_id,
                    after_team_recorded_at=submitted_at + timedelta(minutes=1),
                    submitted_at=submitted_at,
                    completed_at=submitted_at + timedelta(minutes=1),
                ),
            ])
            await session.commit()

            response = await warranty_claim_records_page(
                request=self._build_request(),
                search=None,
                claim_status=None,
                page="1",
                per_page=20,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("legacy-buyer@example.com", html)
        self.assertIn("Before Legacy Team", html)
        self.assertIn("After Legacy Team", html)


if __name__ == "__main__":
    unittest.main()
