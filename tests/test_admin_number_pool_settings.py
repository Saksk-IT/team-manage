import json
import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team
from app.routes.admin import (
    NumberPoolSettingsRequest,
    TeamTransferRequest,
    transfer_team_type,
    update_number_pool_settings,
)
from app.services.team import TEAM_TYPE_NUMBER_POOL, TEAM_TYPE_STANDARD
from app.services.settings import settings_service


class AdminNumberPoolSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        settings_service.clear_cache()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        settings_service.clear_cache()
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_update_number_pool_settings_enables_feature(self):
        async with self.Session() as session:
            response = await update_number_pool_settings(
                pool_data=NumberPoolSettingsRequest(enabled=True),
                db=session,
                current_user={"username": "admin"},
            )
            config = await settings_service.get_number_pool_config(session)

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(config, {"enabled": True})

    async def test_transfer_to_number_pool_requires_feature_enabled(self):
        async with self.Session() as session:
            team = Team(
                email="standard-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-standard",
                team_type=TEAM_TYPE_STANDARD,
                team_name="Standard Team",
                status="active",
                current_members=1,
                max_members=5,
            )
            session.add(team)
            await session.commit()

            response = await transfer_team_type(
                team_id=team.id,
                transfer_data=TeamTransferRequest(target_team_type=TEAM_TYPE_NUMBER_POOL),
                db=session,
                current_user={"username": "admin"},
            )
            refreshed_team = await session.get(Team, team.id)

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertIn("开启号池功能", payload["error"])
        self.assertEqual(refreshed_team.team_type, TEAM_TYPE_STANDARD)

    async def test_update_number_pool_settings_rejects_disable_when_pool_not_empty(self):
        async with self.Session() as session:
            session.add(Team(
                email="pool-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-pool",
                team_type=TEAM_TYPE_NUMBER_POOL,
                team_name="Pool Team",
                status="active",
                current_members=1,
                max_members=5,
            ))
            await session.commit()

            response = await update_number_pool_settings(
                pool_data=NumberPoolSettingsRequest(enabled=False),
                db=session,
                current_user={"username": "admin"},
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["pool_team_count"], 1)
        self.assertIn("号池内仍有 Team", payload["error"])


if __name__ == "__main__":
    unittest.main()
