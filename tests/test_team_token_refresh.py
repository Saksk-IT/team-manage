import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.models import Team
from app.services.team import TeamService


class TeamTokenRefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = TeamService()
        self.db_session = Mock()
        self.db_session.in_transaction = Mock(return_value=True)

    async def test_force_refresh_keeps_current_access_token_when_existing_token_still_valid(self):
        team = Team(
            id=229,
            email="valid@example.com",
            access_token_encrypted="enc-at",
            session_token_encrypted="enc-st",
            refresh_token_encrypted="enc-rt",
            client_id="client-id",
            status="active",
            error_count=0,
        )

        self.service.jwt_parser.is_token_expired = Mock(return_value=False)
        self.service.chatgpt_service.refresh_access_token_with_session_token = AsyncMock(
            return_value={"success": False, "error": "session token expired"}
        )
        self.service.chatgpt_service.refresh_access_token_with_refresh_token = AsyncMock(
            return_value={"success": False, "error": "refresh token unavailable"}
        )

        with patch(
            "app.services.team.encryption_service.decrypt_token",
            side_effect=lambda value: {
                "enc-at": "current-access-token",
                "enc-st": "session-token",
                "enc-rt": "refresh-token",
            }[value],
        ):
            token = await self.service.ensure_access_token(team, self.db_session, force_refresh=True)

        self.assertEqual(token, "current-access-token")
        self.assertEqual(team.status, "active")
        self.assertEqual(team.error_count, 0)
        self.service.chatgpt_service.refresh_access_token_with_session_token.assert_awaited_once()
        self.service.chatgpt_service.refresh_access_token_with_refresh_token.assert_awaited_once()

    async def test_refresh_token_is_still_tried_after_session_token_refresh_failure(self):
        team = Team(
            id=230,
            email="fallback@example.com",
            access_token_encrypted="enc-at",
            session_token_encrypted="enc-st",
            refresh_token_encrypted="enc-rt",
            client_id="client-id",
            status="active",
            error_count=0,
        )

        self.service.jwt_parser.is_token_expired = Mock(return_value=True)
        self.service._reset_error_status = AsyncMock()
        self.service.chatgpt_service.refresh_access_token_with_session_token = AsyncMock(
            return_value={"success": False, "error": "session refresh rejected"}
        )
        self.service.chatgpt_service.refresh_access_token_with_refresh_token = AsyncMock(
            return_value={
                "success": True,
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
            }
        )

        with patch(
            "app.services.team.encryption_service.decrypt_token",
            side_effect=lambda value: {
                "enc-at": "expired-access-token",
                "enc-st": "session-token",
                "enc-rt": "refresh-token",
            }[value],
        ), patch(
            "app.services.team.encryption_service.encrypt_token",
            side_effect=lambda value: f"encrypted::{value}",
        ):
            token = await self.service.ensure_access_token(team, self.db_session, force_refresh=False)

        self.assertEqual(token, "new-access-token")
        self.assertEqual(team.access_token_encrypted, "encrypted::new-access-token")
        self.assertEqual(team.refresh_token_encrypted, "encrypted::new-refresh-token")
        self.service.chatgpt_service.refresh_access_token_with_session_token.assert_awaited_once()
        self.service.chatgpt_service.refresh_access_token_with_refresh_token.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
