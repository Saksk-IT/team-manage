import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.routes.admin import (
    BulkActionRequest,
    BatchActionJobState,
    batch_action_jobs,
    batch_enable_device_auth_stream,
    batch_refresh_teams_stream,
    stop_batch_action,
)


class FakeRequest:
    async def is_disconnected(self):
        return False


async def collect_events(async_iterable):
    events = []
    async for chunk in async_iterable:
        if isinstance(chunk, bytes):
            chunk = chunk.decode('utf-8')
        for line in chunk.splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


async def read_next_event(iterator):
    chunk = await anext(iterator)
    if isinstance(chunk, bytes):
        chunk = chunk.decode('utf-8')
    return json.loads(chunk.strip())


class BatchStreamActionTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        batch_action_jobs.clear()

    async def test_batch_refresh_stream_returns_stage_and_result_events(self):
        force_refresh_calls = []

        async def mock_sync(team_id, db_session, force_refresh=False, progress_callback=None):
            force_refresh_calls.append(force_refresh)
            await progress_callback({
                'stage_key': 'load_team',
                'stage_label': '加载 Team 信息',
                'team_id': team_id,
                'email': f'user{team_id}@example.com',
            })
            return {
                'success': team_id == 1,
                'team_id': team_id,
                'email': f'user{team_id}@example.com',
                'message': '同步成功' if team_id == 1 else None,
                'error': None if team_id == 1 else 'Token 已过期且无法刷新',
            }

        with patch('app.routes.admin.team_service.sync_team_info', new=AsyncMock(side_effect=mock_sync)):
            response = await batch_refresh_teams_stream(
                request=FakeRequest(),
                action_data=BulkActionRequest(ids=[1, 2]),
                db=object(),
                current_user={'username': 'admin'},
            )
            events = await collect_events(response.body_iterator)

        self.assertEqual(events[0]['type'], 'start')
        self.assertEqual(events[0]['action'], 'batch_refresh')
        self.assertEqual(events[0]['total'], 2)
        self.assertEqual([event['type'] for event in events].count('item_stage'), 2)

        item_results = [event for event in events if event['type'] == 'item_result']
        self.assertEqual(len(item_results), 2)
        self.assertEqual(item_results[0]['status'], 'success')
        self.assertEqual(item_results[1]['status'], 'failed')
        self.assertEqual(item_results[1]['message'], 'Token 已过期且无法刷新')

        finish_event = events[-1]
        self.assertEqual(finish_event['type'], 'finish')
        self.assertFalse(finish_event['stopped'])
        self.assertEqual(finish_event['processed_count'], 2)
        self.assertEqual(finish_event['success_count'], 1)
        self.assertEqual(finish_event['failed_count'], 1)
        self.assertEqual(force_refresh_calls, [True, True])

    async def test_batch_enable_device_auth_stream_returns_finish_summary(self):
        async def mock_enable(team_id, db_session, progress_callback=None):
            await progress_callback({
                'stage_key': 'toggle_feature',
                'stage_label': '调用开启验证接口',
                'team_id': team_id,
                'email': f'user{team_id}@example.com',
            })
            return {
                'success': team_id != 2,
                'team_id': team_id,
                'email': f'user{team_id}@example.com',
                'message': '设备代码身份验证开启成功' if team_id != 2 else None,
                'error': None if team_id != 2 else '开启设备身份验证失败: forbidden',
            }

        with patch('app.routes.admin.team_service.enable_device_code_auth', new=AsyncMock(side_effect=mock_enable)):
            response = await batch_enable_device_auth_stream(
                request=FakeRequest(),
                action_data=BulkActionRequest(ids=[1, 2, 3]),
                db=object(),
                current_user={'username': 'admin'},
            )
            events = await collect_events(response.body_iterator)

        item_results = [event for event in events if event['type'] == 'item_result']
        finish_event = events[-1]

        self.assertEqual(len(item_results), 3)
        self.assertEqual(finish_event['type'], 'finish')
        self.assertFalse(finish_event['stopped'])
        self.assertEqual(finish_event['processed_count'], 3)
        self.assertEqual(finish_event['success_count'], 2)
        self.assertEqual(finish_event['failed_count'], 1)
        self.assertIn('批量开启验证已完成', finish_event['summary'])

    async def test_stop_endpoint_stops_stream_after_current_item(self):
        release_first_item = asyncio.Event()
        started_team_ids = []

        async def mock_sync(team_id, db_session, force_refresh=False, progress_callback=None):
            started_team_ids.append(team_id)
            await progress_callback({
                'stage_key': 'load_team',
                'stage_label': '加载 Team 信息',
                'team_id': team_id,
                'email': f'user{team_id}@example.com',
            })
            if team_id == 1:
                await release_first_item.wait()
            return {
                'success': True,
                'team_id': team_id,
                'email': f'user{team_id}@example.com',
                'message': '同步成功',
                'error': None,
            }

        with patch('app.routes.admin.team_service.sync_team_info', new=AsyncMock(side_effect=mock_sync)):
            response = await batch_refresh_teams_stream(
                request=FakeRequest(),
                action_data=BulkActionRequest(ids=[1, 2, 3]),
                db=object(),
                current_user={'username': 'admin'},
            )

            iterator = response.body_iterator.__aiter__()
            start_event = await read_next_event(iterator)
            stage_event = await read_next_event(iterator)

            self.assertEqual(start_event['type'], 'start')
            self.assertEqual(stage_event['type'], 'item_stage')
            self.assertEqual(stage_event['team_id'], 1)

            stop_response = await stop_batch_action(job_id=start_event['job_id'], current_user={'username': 'admin'})
            stop_payload = json.loads(stop_response.body.decode('utf-8'))
            self.assertTrue(stop_payload['success'])

            release_first_item.set()
            remaining_events = await collect_events(iterator)

        item_results = [event for event in remaining_events if event['type'] == 'item_result']
        finish_event = remaining_events[-1]

        self.assertEqual(started_team_ids, [1])
        self.assertEqual(len(item_results), 1)
        self.assertEqual(item_results[0]['team_id'], 1)
        self.assertTrue(finish_event['stopped'])
        self.assertEqual(finish_event['processed_count'], 1)
        self.assertEqual(finish_event['success_count'], 1)
        self.assertEqual(finish_event['failed_count'], 0)

    async def test_stop_endpoint_returns_404_for_unknown_job(self):
        response = await stop_batch_action(job_id='missing-job', current_user={'username': 'admin'})
        payload = json.loads(response.body.decode('utf-8'))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(payload['success'])


if __name__ == '__main__':
    unittest.main()
