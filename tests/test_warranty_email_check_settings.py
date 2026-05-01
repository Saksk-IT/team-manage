import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.settings import settings_service


class WarrantyEmailCheckSettingsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_get_warranty_email_check_config_defaults_to_disabled(self):
        async with self.Session() as session:
            config = await settings_service.get_warranty_email_check_config(session)

        self.assertFalse(config["enabled"])
        self.assertIn("质保邮箱列表", config["match_content"])
        self.assertIn("未查询到", config["miss_content"])

    async def test_update_warranty_email_check_config_sanitizes_rich_text(self):
        async with self.Session() as session:
            success = await settings_service.update_warranty_email_check_config(
                session,
                True,
                '<p><strong>通过</strong><script>alert(1)</script><a href="javascript:alert(1)">坏链接</a></p>',
                '<p>未通过</p><img src=x onerror=alert(1)>',
            )
            config = await settings_service.get_warranty_email_check_config(session)

        self.assertTrue(success)
        self.assertTrue(config["enabled"])
        self.assertIn("<strong>通过</strong>", config["match_content"])
        self.assertNotIn("<script", config["match_content"])
        self.assertNotIn("javascript:", config["match_content"])
        self.assertIn("未通过", config["miss_content"])
        self.assertNotIn("<img", config["miss_content"])


if __name__ == "__main__":
    unittest.main()
