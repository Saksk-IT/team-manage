import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import RedemptionCode, Team
from app.routes.admin import admin_dashboard
from app.services.team import TeamService


class TeamMultiFilterTests(unittest.IsolatedAsyncioTestCase):
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

    def _build_request(self, path: str = "/admin") -> Request:
        return Request({"type": "http", "method": "GET", "path": path, "headers": []})

    async def _seed_teams(self, session):
        matched_team = Team(
            email="matched@example.com",
            access_token_encrypted="dummy-token",
            account_id="acc-matched",
            team_name="Matched Team",
            status="active",
            current_members=3,
            max_members=5,
            device_code_auth_enabled=True,
            created_at=datetime(2026, 4, 10, 9, 0, 0),
            expires_at=datetime(2026, 6, 15, 23, 0, 0),
        )
        wrong_import_time_team = Team(
            email="old@example.com",
            access_token_encrypted="dummy-token",
            account_id="acc-old",
            team_name="Old Team",
            status="active",
            current_members=3,
            max_members=5,
            device_code_auth_enabled=True,
            created_at=datetime(2026, 3, 31, 23, 59, 59),
            expires_at=datetime(2026, 6, 15, 23, 0, 0),
        )
        wrong_expiry_team = Team(
            email="late@example.com",
            access_token_encrypted="dummy-token",
            account_id="acc-late",
            team_name="Late Expiry Team",
            status="active",
            current_members=3,
            max_members=5,
            device_code_auth_enabled=True,
            created_at=datetime(2026, 4, 10, 9, 0, 0),
            expires_at=datetime(2026, 7, 1, 0, 0, 0),
        )
        wrong_device_team = Team(
            email="device-off@example.com",
            access_token_encrypted="dummy-token",
            account_id="acc-device-off",
            team_name="Device Off Team",
            status="active",
            current_members=3,
            max_members=5,
            device_code_auth_enabled=False,
            created_at=datetime(2026, 4, 10, 9, 0, 0),
            expires_at=datetime(2026, 6, 15, 23, 0, 0),
        )
        wrong_status_team = Team(
            email="full@example.com",
            access_token_encrypted="dummy-token",
            account_id="acc-full",
            team_name="Full Team",
            status="full",
            current_members=3,
            max_members=5,
            device_code_auth_enabled=True,
            created_at=datetime(2026, 4, 10, 9, 0, 0),
            expires_at=datetime(2026, 6, 15, 23, 0, 0),
        )
        wrong_member_team = Team(
            email="crowded@example.com",
            access_token_encrypted="dummy-token",
            account_id="acc-crowded",
            team_name="Crowded Team",
            status="active",
            current_members=6,
            max_members=8,
            device_code_auth_enabled=True,
            created_at=datetime(2026, 4, 10, 9, 0, 0),
            expires_at=datetime(2026, 6, 15, 23, 0, 0),
        )
        session.add_all([
            matched_team,
            wrong_import_time_team,
            wrong_expiry_team,
            wrong_device_team,
            wrong_status_team,
            wrong_member_team,
        ])
        await session.commit()
        return matched_team

    async def test_service_filters_teams_by_console_multi_filters(self):
        async with self.Session() as session:
            matched_team = await self._seed_teams(session)

            result = await self.service.get_all_teams(
                session,
                status="active",
                imported_from=datetime(2026, 4, 1, 0, 0, 0),
                imported_to=datetime(2026, 4, 30, 23, 59, 59),
                expires_from=datetime(2026, 6, 1, 0, 0, 0),
                expires_to=datetime(2026, 6, 30, 23, 59, 59),
                device_auth_enabled=True,
                members_min=2,
                members_max=4,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["teams"][0]["id"], matched_team.id)

    async def test_admin_dashboard_renders_and_applies_console_filter_form(self):
        async with self.Session() as session:
            await self._seed_teams(session)

            response = await admin_dashboard(
                request=self._build_request(),
                page=1,
                per_page=20,
                search=None,
                status="active",
                imported_from="2026-04-01",
                imported_to="2026-04-30",
                expires_from="2026-06-01",
                expires_to="2026-06-30",
                device_auth="enabled",
                members_min="2",
                members_max="4",
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("Matched Team", html)
        self.assertNotIn("Old Team", html)
        self.assertNotIn("Late Expiry Team", html)
        self.assertNotIn("Device Off Team", html)
        self.assertNotIn("Full Team", html)
        self.assertNotIn("Crowded Team", html)
        self.assertIn('name="expires_from" value="2026-06-01"', html)
        self.assertIn('name="device_auth"', html)
        self.assertIn('name="members_min" value="2"', html)

    async def test_admin_dashboard_stats_show_seats_instead_of_codes(self):
        async with self.Session() as session:
            session.add_all([
                Team(
                    email="owner-one@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-one",
                    team_name="Seat Team One",
                    status="active",
                    current_members=1,
                    max_members=9,
                ),
                Team(
                    email="owner-two@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-two",
                    team_name="Seat Team Two",
                    status="active",
                    current_members=4,
                    max_members=9,
                ),
                RedemptionCode(code="UNUSED-CODE-001", status="unused"),
                RedemptionCode(code="USED-CODE-001", status="used"),
            ])
            await session.commit()

            response = await admin_dashboard(
                request=self._build_request(),
                page=1,
                per_page=20,
                search=None,
                status=None,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertNotIn("兑换码总数", html)
        self.assertNotIn("已使用兑换码", html)
        self.assertRegex(
            html,
            r'<div class="stat-value">\s*16\s*</div>\s*<div class="stat-label">所有席位</div>',
        )
        self.assertRegex(
            html,
            r'<div class="stat-value">\s*13\s*</div>\s*<div class="stat-label">可用席位</div>',
        )


if __name__ == "__main__":
    unittest.main()
