import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.settings import settings_service


class WarrantyFakeSuccessSettingsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_get_warranty_fake_success_config_defaults_to_false(self):
        async with self.Session() as session:
            config = await settings_service.get_warranty_fake_success_config(session)

        self.assertEqual(config, {"enabled": False})

    async def test_update_warranty_fake_success_config_persists_value(self):
        async with self.Session() as session:
            success = await settings_service.update_warranty_fake_success_config(session, True)
            config = await settings_service.get_warranty_fake_success_config(session)

        self.assertTrue(success)
        self.assertEqual(config, {"enabled": True})

    async def test_get_warranty_fake_success_remaining_spots_initializes_in_range(self):
        async with self.Session() as session:
            remaining_spots = await settings_service.get_warranty_fake_success_remaining_spots(session)

        self.assertGreaterEqual(remaining_spots, settings_service.WARRANTY_FAKE_SUCCESS_MIN_SPOTS)
        self.assertLessEqual(remaining_spots, settings_service.WARRANTY_FAKE_SUCCESS_MAX_SPOTS)

    async def test_decrement_warranty_fake_success_remaining_spots_stops_at_minimum(self):
        async with self.Session() as session:
            await settings_service.update_setting(
                session,
                settings_service.WARRANTY_FAKE_SUCCESS_REMAINING_SPOTS_KEY,
                str(settings_service.WARRANTY_FAKE_SUCCESS_MIN_SPOTS)
            )

            remaining_spots = await settings_service.decrement_warranty_fake_success_remaining_spots(session)

        self.assertEqual(remaining_spots, settings_service.WARRANTY_FAKE_SUCCESS_MIN_SPOTS)


if __name__ == "__main__":
    unittest.main()
