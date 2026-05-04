import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.settings import settings_service


class WarrantySuperCodeSettingsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_save_and_match_dual_super_codes(self):
        async with self.Session() as session:
            await settings_service.save_warranty_super_code_config(
                session,
                settings_service.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT,
                "usage-code-1234",
                3
            )
            await settings_service.save_warranty_super_code_config(
                session,
                settings_service.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT,
                "time-code-5678",
                15
            )

            configs = await settings_service.get_warranty_super_code_configs(session)
            usage_match = await settings_service.match_warranty_super_code(session, "usage-code-1234")
            time_match = await settings_service.match_warranty_super_code(session, "time-code-5678")

        self.assertEqual(configs["usage_limit"]["max_uses"], 3)
        self.assertEqual(configs["time_limit"]["days"], 15)
        self.assertEqual(usage_match["type"], "usage_limit")
        self.assertEqual(time_match["type"], "time_limit")

    async def test_same_code_is_rejected_between_two_types(self):
        async with self.Session() as session:
            await settings_service.save_warranty_super_code_config(
                session,
                settings_service.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT,
                "DUP-CODE-1234",
                2
            )

            with self.assertRaises(ValueError):
                await settings_service.save_warranty_super_code_config(
                    session,
                    settings_service.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT,
                    "DUP-CODE-1234",
                    15
                )

    async def test_disable_clears_code_and_limit(self):
        async with self.Session() as session:
            await settings_service.save_warranty_super_code_config(
                session,
                settings_service.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT,
                "TIME-CODE-5678",
                30
            )
            await settings_service.disable_warranty_super_code_config(
                session,
                settings_service.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT
            )

            configs = await settings_service.get_warranty_super_code_configs(session)

        self.assertFalse(configs["time_limit"]["enabled"])
        self.assertEqual(configs["time_limit"]["code"], "")
        self.assertIsNone(configs["time_limit"]["days"])

    async def test_email_check_super_code_regenerate_invalidates_previous_code(self):
        async with self.Session() as session:
            first = await settings_service.regenerate_warranty_email_check_super_code(session)
            first_code = first["code"]
            self.assertTrue(first_code)
            self.assertTrue(await settings_service.match_warranty_email_check_super_code(session, first_code.lower()))

            second = await settings_service.regenerate_warranty_email_check_super_code(session)
            second_code = second["code"]

            self.assertTrue(second_code)
            self.assertNotEqual(first_code, second_code)
            self.assertFalse(await settings_service.match_warranty_email_check_super_code(session, first_code))
            self.assertTrue(await settings_service.match_warranty_email_check_super_code(session, second_code))



if __name__ == "__main__":
    unittest.main()
