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
        self.assertFalse(config["ignore_team_status"])
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

    async def test_update_warranty_email_check_config_keeps_uploaded_images(self):
        image_path = os.path.join(os.path.dirname(self.db_path), "uploads", "warranty-email-check", "guide.png")
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        with open(image_path, "wb") as image_file:
            image_file.write(b"fake-image")

        async with self.Session() as session:
            success = await settings_service.update_warranty_email_check_config(
                session,
                True,
                '<p>通过</p><img src="/uploads/warranty-email-check/guide.png" alt="教程图片" style="max-width: 100%; height: auto;" onerror="alert(1)">',
                '<p>未通过</p>',
            )
            config = await settings_service.get_warranty_email_check_config(session)

        self.assertTrue(success)
        self.assertIn('<img src="/uploads/warranty-email-check/guide.png"', config["match_content"])
        self.assertIn('alt="教程图片"', config["match_content"])
        self.assertIn("max-width: 100%;", config["match_content"])
        self.assertNotIn("onerror", config["match_content"])

    async def test_update_warranty_email_check_config_strips_non_image_upload_path(self):
        async with self.Session() as session:
            success = await settings_service.update_warranty_email_check_config(
                session,
                True,
                '<p>通过</p><img src="/uploads/warranty-email-check/readme.txt" alt="非法文件">',
                '<p>未通过</p>',
            )
            config = await settings_service.get_warranty_email_check_config(session)

        self.assertTrue(success)
        self.assertIn("通过", config["match_content"])
        self.assertNotIn("<img", config["match_content"])

    async def test_update_warranty_email_check_config_supports_template_lists(self):
        async with self.Session() as session:
            success = await settings_service.update_warranty_email_check_config(
                session,
                True,
                match_templates=[
                    {"id": "match-a", "name": "命中 A", "content": "<p>A</p>"},
                    {"id": "match-b", "name": "命中 B", "content": "<p><script>bad()</script>B</p>"},
                ],
                miss_templates=[
                    {"id": "miss-a", "name": "未命中 A", "content": "<p>未命中</p>"},
                ],
            )
            config = await settings_service.get_warranty_email_check_config(session)

        self.assertTrue(success)
        self.assertEqual([item["id"] for item in config["match_templates"]], ["match-a", "match-b"])
        self.assertEqual(config["match_templates"][0]["content"], "<p>A</p>")
        self.assertIn("B", config["match_templates"][1]["content"])
        self.assertNotIn("<script", config["match_templates"][1]["content"])
        self.assertEqual(config["match_content"], "<p>A</p>")
        self.assertEqual(config["miss_templates"][0]["id"], "miss-a")

    async def test_get_warranty_email_check_config_falls_back_to_legacy_content_as_template(self):
        async with self.Session() as session:
            success = await settings_service.update_warranty_email_check_config(
                session,
                True,
                "<p>旧命中</p>",
                "<p>旧未命中</p>",
                ignore_team_status=True,
            )
            config = await settings_service.get_warranty_email_check_config(session)

        self.assertTrue(success)
        self.assertTrue(config["ignore_team_status"])
        self.assertEqual(config["match_templates"][0]["id"], "match-default")
        self.assertEqual(config["match_templates"][0]["content"], "<p>旧命中</p>")
        self.assertEqual(config["miss_templates"][0]["id"], "miss-default")
        self.assertEqual(config["miss_templates"][0]["content"], "<p>旧未命中</p>")


if __name__ == "__main__":
    unittest.main()
