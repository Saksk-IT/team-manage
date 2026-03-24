import unittest
from unittest.mock import AsyncMock, Mock

from app.models import Team
from app.services.team import TeamService


class ScalarResult:
    def __init__(self, team):
        self._team = team

    def scalar_one_or_none(self):
        return self._team


class TeamProgressCallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = TeamService()
        self.db_session = Mock()
        self.db_session.execute = AsyncMock()
        self.db_session.in_transaction = Mock(return_value=True)
        self.db_session.flush = AsyncMock()
        self.db_session.commit = AsyncMock()
        self.db_session.rollback = AsyncMock()

    async def test_sync_team_info_emits_progress_stages_in_order(self):
        team = Team(
            id=11,
            email='sync@example.com',
            account_id='acc-1',
            max_members=5,
            device_code_auth_enabled=False,
            status='active',
            error_count=0,
        )
        self.db_session.execute.return_value = ScalarResult(team)

        self.service.ensure_access_token = AsyncMock(return_value='access-token')
        self.service.jwt_parser.extract_email = Mock(return_value='sync@example.com')
        self.service.chatgpt_service.get_account_info = AsyncMock(return_value={
            'success': True,
            'accounts': [{
                'account_id': 'acc-1',
                'name': 'Sync Team',
                'plan_type': 'team',
                'subscription_plan': 'chatgptteamplan',
                'expires_at': None,
                'has_active_subscription': True,
                'account_user_role': 'account-owner',
            }],
        })
        self.service.chatgpt_service.get_members = AsyncMock(return_value={
            'success': True,
            'total': 2,
            'members': [{'email': 'a@example.com'}, {'email': 'b@example.com'}],
        })
        self.service.chatgpt_service.get_invites = AsyncMock(return_value={
            'success': True,
            'total': 1,
            'items': [{'email_address': 'c@example.com'}],
        })
        self.service.chatgpt_service.get_account_settings = AsyncMock(return_value={
            'success': True,
            'data': {'beta_settings': {'codex_device_code_auth': True}},
        })

        progress_events = []

        async def progress_callback(payload):
            progress_events.append(payload)

        result = await self.service.sync_team_info(
            team_id=11,
            db_session=self.db_session,
            force_refresh=True,
            progress_callback=progress_callback,
        )

        self.assertTrue(result['success'])
        self.assertEqual(
            [event['stage_key'] for event in progress_events],
            ['load_team', 'ensure_token', 'fetch_account_info', 'fetch_members', 'persist_result']
        )

    async def test_enable_device_code_auth_emits_progress_before_failure(self):
        team = Team(
            id=22,
            email='device@example.com',
            account_id='acc-22',
            status='active',
        )
        self.db_session.execute.return_value = ScalarResult(team)

        self.service.ensure_access_token = AsyncMock(return_value='access-token')
        self.service.chatgpt_service.toggle_beta_feature = AsyncMock(return_value={
            'success': False,
            'error': 'forbidden',
        })

        progress_events = []

        async def progress_callback(payload):
            progress_events.append(payload)

        result = await self.service.enable_device_code_auth(
            team_id=22,
            db_session=self.db_session,
            progress_callback=progress_callback,
        )

        self.assertFalse(result['success'])
        self.assertEqual(
            [event['stage_key'] for event in progress_events],
            ['load_team', 'ensure_token', 'toggle_feature']
        )


if __name__ == '__main__':
    unittest.main()
