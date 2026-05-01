import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.admin_sidebar import (
    get_admin_sidebar_items,
    get_admin_sidebar_items_for_user,
    get_default_admin_sidebar_order,
)
from app.services.settings import settings_service


class AdminSidebarOrderSettingsTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_get_admin_sidebar_order_defaults_to_builtin_order(self):
        async with self.Session() as session:
            order = await settings_service.get_admin_sidebar_order(session)

        self.assertEqual(order, get_default_admin_sidebar_order())
        self.assertIn("team_member_snapshots", order)
        self.assertIn("warranty_email_check", order)


    async def test_get_admin_sidebar_order_drops_legacy_warranty_team_item(self):
        async with self.Session() as session:
            await settings_service.update_setting(
                session,
                settings_service.ADMIN_SIDEBAR_ORDER_KEY,
                '["dashboard", "warranty_teams", "codes"]'
            )
            order = await settings_service.get_admin_sidebar_order(session)

        self.assertNotIn("warranty_teams", order)
        self.assertEqual(order[0], "dashboard")
        self.assertEqual(order[1], "codes")
        self.assertEqual(set(order), set(get_default_admin_sidebar_order()))

    async def test_update_admin_sidebar_order_persists_normalized_order(self):
        async with self.Session() as session:
            saved_order = await settings_service.update_admin_sidebar_order(
                session,
                ["settings", "dashboard"]
            )
            loaded_order = await settings_service.get_admin_sidebar_order(session)

        self.assertEqual(saved_order[:2], ["settings", "dashboard"])
        self.assertEqual(loaded_order, saved_order)
        self.assertEqual(set(loaded_order), set(get_default_admin_sidebar_order()))
        self.assertIn("team_member_snapshots", loaded_order)

    async def test_update_admin_sidebar_order_rejects_unknown_item(self):
        async with self.Session() as session:
            with self.assertRaises(ValueError):
                await settings_service.update_admin_sidebar_order(session, ["dashboard", "unknown"])

    def test_number_pool_sidebar_item_can_be_hidden_when_disabled(self):
        order = get_default_admin_sidebar_order()

        hidden_items = get_admin_sidebar_items(order, number_pool_enabled=False)
        visible_items = get_admin_sidebar_items(order, number_pool_enabled=True)
        user_hidden_items = get_admin_sidebar_items_for_user(
            {"username": "admin", "is_super_admin": True},
            order,
            number_pool_enabled=False,
        )

        self.assertNotIn("number_pool", [item["id"] for item in hidden_items])
        self.assertIn("number_pool", [item["id"] for item in visible_items])
        self.assertNotIn("number_pool", [item["id"] for item in user_hidden_items])

    def test_warranty_email_check_sidebar_item_links_to_standalone_page(self):
        items = get_admin_sidebar_items(get_default_admin_sidebar_order())
        warranty_email_check_item = next(
            item for item in items if item["id"] == "warranty_email_check"
        )

        self.assertEqual(warranty_email_check_item["href"], "/admin/warranty-email-check")
        self.assertEqual(warranty_email_check_item["active_page"], "warranty_email_check")
        self.assertEqual(warranty_email_check_item["label"], "质保名单判定")


if __name__ == "__main__":
    unittest.main()
