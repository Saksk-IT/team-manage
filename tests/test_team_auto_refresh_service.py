import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team
from app.services.settings import settings_service
from app.services.team import TeamService
from app.services.team_auto_refresh import TeamAutoRefreshService
from app.utils.time_utils import get_now


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TeamAutoRefreshServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_syncs_only_one_due_team_when_enabled(self):
        service = TeamAutoRefreshService()
        fake_sessions = []

        def session_factory():
            session = AsyncMock()
            fake_sessions.append(session)
            return FakeSessionContext(session)

        with (
            patch.object(
                service,
                "_get_runtime_config",
                new=AsyncMock(return_value={"enabled": True, "interval_minutes": 5})
            ),
            patch.object(
                service,
                "_get_refreshable_team_ids",
                new=AsyncMock(return_value=[11])
            ) as mocked_ids,
            patch("app.services.team_auto_refresh.AsyncSessionLocal", side_effect=session_factory),
            patch(
                "app.services.team_auto_refresh.team_service.refresh_team_state",
                new=AsyncMock(return_value={"success": True, "message": "同步成功", "error": None})
            ) as mocked_refresh,
        ):
            interval = await service.run_once()

        self.assertEqual(interval, 5)
        mocked_ids.assert_awaited_once_with(interval_minutes=5, limit=1)
        self.assertEqual(len(fake_sessions), 1)
        fake_sessions[0].commit.assert_awaited_once()
        self.assertEqual(mocked_refresh.await_count, 1)
        self.assertEqual(mocked_refresh.await_args_list[0].args[0], 11)
        self.assertFalse(mocked_refresh.await_args_list[0].kwargs["force_refresh"])
        self.assertEqual(mocked_refresh.await_args_list[0].kwargs["source"], "auto")

    async def test_run_once_skips_sync_when_disabled(self):
        service = TeamAutoRefreshService()

        with (
            patch.object(
                service,
                "_get_runtime_config",
                new=AsyncMock(return_value={"enabled": False, "interval_minutes": 9})
            ),
            patch.object(service, "_get_refreshable_team_ids", new=AsyncMock()) as mocked_ids,
            patch(
                "app.services.team_auto_refresh.team_service.refresh_team_state",
                new=AsyncMock()
            ) as mocked_refresh,
        ):
            interval = await service.run_once()

        self.assertEqual(interval, 9)
        mocked_ids.assert_not_awaited()
        mocked_refresh.assert_not_awaited()

    async def test_get_refreshable_team_ids_excludes_banned_deactivated_workspace_team(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with Session() as session:
                session.add_all([
                    Team(
                        email="active@example.com",
                        access_token_encrypted="enc-active",
                        account_id="acc-active",
                        team_type="standard",
                        status="active",
                        current_members=1,
                        max_members=5,
                    ),
                    Team(
                        email="deactivated@example.com",
                        access_token_encrypted="enc-banned",
                        account_id="acc-banned",
                        team_type="standard",
                        status="banned",
                        current_members=1,
                        max_members=5,
                    ),
                ])
                await session.commit()

            service = TeamAutoRefreshService()
            with patch("app.services.team_auto_refresh.AsyncSessionLocal", Session):
                refreshable_ids = await service._get_refreshable_team_ids(
                    interval_minutes=5,
                    limit=1,
                )

            async with Session() as session:
                active_team = await session.scalar(
                    select(Team).where(Team.email == "active@example.com")
                )

            self.assertEqual(refreshable_ids, [active_team.id])
        finally:
            await engine.dispose()
            if os.path.exists(db_path):
                os.remove(db_path)

    async def test_get_refreshable_team_ids_returns_one_oldest_due_team(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            now = get_now()
            async with Session() as session:
                never_refreshed = Team(
                    email="never@example.com",
                    access_token_encrypted="enc-never",
                    account_id="acc-never",
                    team_type="standard",
                    status="active",
                    current_members=1,
                    max_members=5,
                    last_refresh_at=None,
                )
                old_refreshed = Team(
                    email="old@example.com",
                    access_token_encrypted="enc-old",
                    account_id="acc-old",
                    team_type="standard",
                    status="active",
                    current_members=1,
                    max_members=5,
                    last_refresh_at=now - timedelta(minutes=41),
                )
                recent_refreshed = Team(
                    email="recent@example.com",
                    access_token_encrypted="enc-recent",
                    account_id="acc-recent",
                    team_type="standard",
                    status="active",
                    current_members=1,
                    max_members=5,
                    last_refresh_at=now - timedelta(minutes=10),
                )
                session.add_all([never_refreshed, old_refreshed, recent_refreshed])
                await session.commit()

                never_id = never_refreshed.id

            service = TeamAutoRefreshService()
            with patch("app.services.team_auto_refresh.AsyncSessionLocal", Session):
                refreshable_ids = await service._get_refreshable_team_ids(
                    interval_minutes=40,
                    limit=1,
                )

            self.assertEqual(refreshable_ids, [never_id])
        finally:
            await engine.dispose()
            if os.path.exists(db_path):
                os.remove(db_path)

    async def test_deactivated_workspace_refresh_marks_banned_and_excludes_from_auto_refresh(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with Session() as session:
                team = Team(
                    email="deactivated@example.com",
                    access_token_encrypted="enc",
                    account_id="acc-deactivated",
                    team_type="standard",
                    status="active",
                    current_members=1,
                    max_members=5,
                )
                session.add(team)
                await session.commit()
                team_id = team.id

                team_service = TeamService()
                team_service.ensure_access_token = AsyncMock(return_value="access-token")
                team_service.jwt_parser.extract_email = Mock(return_value="deactivated@example.com")
                team_service.chatgpt_service.get_account_info = AsyncMock(return_value={
                    "success": False,
                    "error": "workspace 已停用",
                    "error_code": "deactivated_workspace",
                })

                result = await team_service.refresh_team_state(team_id, session)
                await session.commit()

            async with Session() as session:
                refreshed_team = await session.get(Team, team_id)

            auto_refresh_service = TeamAutoRefreshService()
            with patch("app.services.team_auto_refresh.AsyncSessionLocal", Session):
                refreshable_ids = await auto_refresh_service._get_refreshable_team_ids(
                    interval_minutes=5,
                    limit=1,
                )

            self.assertFalse(result["success"])
            self.assertEqual(result["error_code"], "deactivated_workspace")
            self.assertEqual(refreshed_team.status, "banned")
            self.assertNotIn(team_id, refreshable_ids)
        finally:
            await engine.dispose()
            if os.path.exists(db_path):
                os.remove(db_path)


class TeamAutoRefreshSettingsConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_team_auto_refresh_config_uses_default_when_missing(self):
        session = Mock()

        with patch.object(
            settings_service,
            "get_setting",
            new=AsyncMock(side_effect=[None, None])
        ):
            config = await settings_service.get_team_auto_refresh_config(session)

        self.assertTrue(config["enabled"])
        self.assertEqual(
            config["interval_minutes"],
            settings_service.DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES
        )

    async def test_get_team_auto_refresh_config_uses_default_for_invalid_interval(self):
        session = Mock()

        with patch.object(
            settings_service,
            "get_setting",
            new=AsyncMock(side_effect=["true", "99999"])
        ):
            config = await settings_service.get_team_auto_refresh_config(session)

        self.assertTrue(config["enabled"])
        self.assertEqual(
            config["interval_minutes"],
            settings_service.DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES
        )


if __name__ == "__main__":
    unittest.main()
