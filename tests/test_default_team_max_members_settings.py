import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.settings import settings_service


class DefaultTeamMaxMembersSettingsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_get_default_team_max_members_defaults_to_five(self):
        async with self.Session() as session:
            value = await settings_service.get_default_team_max_members(session)

        self.assertEqual(value, 5)

    async def test_update_default_team_max_members_persists_value(self):
        async with self.Session() as session:
            success = await settings_service.update_default_team_max_members(session, 8)
            value = await settings_service.get_default_team_max_members(session)

        self.assertTrue(success)
        self.assertEqual(value, 8)

    async def test_update_default_team_max_members_rejects_invalid_value(self):
        async with self.Session() as session:
            with self.assertRaises(ValueError):
                await settings_service.update_default_team_max_members(session, 0)


if __name__ == "__main__":
    unittest.main()
