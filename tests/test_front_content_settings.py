import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.settings import settings_service


class FrontContentSettingsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_get_front_announcement_config_defaults_to_disabled(self):
        async with self.Session() as session:
            config = await settings_service.get_front_announcement_config(session)

        self.assertEqual(config, {"enabled": False, "content": ""})

    async def test_update_front_announcement_config_persists_value(self):
        async with self.Session() as session:
            success = await settings_service.update_front_announcement_config(
                session,
                True,
                "系统公告：维护通知"
            )
            config = await settings_service.get_front_announcement_config(session)

        self.assertTrue(success)
        self.assertEqual(config, {"enabled": True, "content": "系统公告：维护通知"})

    async def test_get_customer_service_config_defaults_to_disabled(self):
        async with self.Session() as session:
            config = await settings_service.get_customer_service_config(session)

        self.assertEqual(
            config,
            {
                "enabled": False,
                "qr_code_url": "",
                "link_url": "",
                "link_text": "",
                "text_content": ""
            }
        )

    async def test_update_customer_service_config_persists_value(self):
        async with self.Session() as session:
            success = await settings_service.update_customer_service_config(
                session,
                True,
                "https://example.com/qrcode.png",
                "https://example.com/contact",
                "",
                "微信：support001"
            )
            config = await settings_service.get_customer_service_config(session)

        self.assertTrue(success)
        self.assertEqual(config["enabled"], True)
        self.assertEqual(config["qr_code_url"], "https://example.com/qrcode.png")
        self.assertEqual(config["link_url"], "https://example.com/contact")
        self.assertEqual(config["link_text"], "立即联系")
        self.assertEqual(config["text_content"], "微信：support001")

    async def test_get_customer_service_config_hides_missing_uploaded_image(self):
        async with self.Session() as session:
            success = await settings_service.update_customer_service_config(
                session,
                True,
                "/uploads/customer-service/missing.png",
                "",
                "",
                ""
            )
            config = await settings_service.get_customer_service_config(session)

        self.assertTrue(success)
        self.assertEqual(config["qr_code_url"], "")

    async def test_get_customer_service_config_prefers_persistent_uploaded_image_url(self):
        with patch(
            "app.services.settings.resolve_customer_service_upload_display_url",
            return_value="/uploads/customer-service/qrcode.png"
        ):
            async with self.Session() as session:
                success = await settings_service.update_customer_service_config(
                    session,
                    True,
                    "/static/uploads/customer-service/qrcode.png",
                    "",
                    "",
                    ""
                )
                config = await settings_service.get_customer_service_config(session)

        self.assertTrue(success)
        self.assertEqual(config["qr_code_url"], "/uploads/customer-service/qrcode.png")


if __name__ == "__main__":
    unittest.main()
