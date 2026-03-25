import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services.settings import settings_service
from app.services.team_auto_refresh import TeamAutoRefreshService


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TeamAutoRefreshServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_syncs_refreshable_teams_when_enabled(self):
        service = TeamAutoRefreshService()
        fake_sessions = []

        def session_factory():
            session = AsyncMock()
            fake_sessions.append(session)
            return FakeSessionContext(session)

        sync_results = [
            {"success": True, "message": "同步成功", "error": None},
            {"success": False, "message": None, "error": "Token 已过期且无法刷新"},
        ]

        with (
            patch.object(
                service,
                "_get_runtime_config",
                new=AsyncMock(return_value={"enabled": True, "interval_minutes": 5})
            ),
            patch.object(
                service,
                "_get_refreshable_team_ids",
                new=AsyncMock(return_value=[11, 22])
            ),
            patch("app.services.team_auto_refresh.AsyncSessionLocal", side_effect=session_factory),
            patch(
                "app.services.team_auto_refresh.team_service.sync_team_info",
                new=AsyncMock(side_effect=sync_results)
            ) as mocked_sync,
        ):
            interval = await service.run_once()

        self.assertEqual(interval, 5)
        self.assertEqual(len(fake_sessions), 2)
        fake_sessions[0].commit.assert_awaited_once()
        fake_sessions[1].commit.assert_awaited_once()
        self.assertEqual(mocked_sync.await_count, 2)
        self.assertEqual(mocked_sync.await_args_list[0].args[0], 11)
        self.assertEqual(mocked_sync.await_args_list[1].args[0], 22)
        self.assertFalse(mocked_sync.await_args_list[0].kwargs["force_refresh"])
        self.assertFalse(mocked_sync.await_args_list[1].kwargs["force_refresh"])

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
                "app.services.team_auto_refresh.team_service.sync_team_info",
                new=AsyncMock()
            ) as mocked_sync,
        ):
            interval = await service.run_once()

        self.assertEqual(interval, 9)
        mocked_ids.assert_not_awaited()
        mocked_sync.assert_not_awaited()


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
