import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Team, WarrantyEmailEntry, WarrantyEmailTemplateLock
from app.services.warranty import WarrantyService
from app.utils.time_utils import get_now


class WarrantyEmailTemplateLockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_email_first_query_randomly_locks_template_and_reuses_it(self):
        service = WarrantyService()
        match_templates = [
            {"id": "match-a", "content": "<p>A</p>"},
            {"id": "match-b", "content": "<p>B</p>"},
        ]
        miss_templates = [{"id": "miss-a", "content": "<p>未命中</p>"}]

        async with self.Session() as session:
            session.add(WarrantyEmailEntry(email="buyer@example.com", remaining_claims=1, last_redeem_code="CODE-A"))
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="match-b") as mocked_choice:
                first_result = await service.check_warranty_email_membership(
                    session,
                    "Buyer@Example.com",
                    warranty_code="CODE-A",
                    match_templates=match_templates,
                    miss_templates=miss_templates,
                )
                second_result = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    warranty_code="CODE-A",
                    match_templates=match_templates,
                    miss_templates=miss_templates,
                )

            locks = (await session.execute(select(WarrantyEmailTemplateLock))).scalars().all()

        mocked_choice.assert_called_once_with(["match-a", "match-b"])
        self.assertTrue(first_result["matched"])
        self.assertEqual(first_result["template_key"], "match-b")
        self.assertEqual(second_result["template_key"], "match-b")
        self.assertTrue(second_result["template_matched"])
        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0].email, "buyer@example.com")
        self.assertTrue(locks[0].matched)
        self.assertEqual(locks[0].template_key, "match-b")

    async def test_unmatched_email_locks_miss_template(self):
        service = WarrantyService()

        async with self.Session() as session:
            with patch("app.services.warranty.secrets.choice", return_value="miss-b"):
                result = await service.check_warranty_email_membership(
                    session,
                    "none@example.com",
                    warranty_code="CODE-A",
                    match_templates=[{"id": "match-a", "content": "<p>A</p>"}],
                    miss_templates=[
                        {"id": "miss-a", "content": "<p>A</p>"},
                        {"id": "miss-b", "content": "<p>B</p>"},
                    ],
                )
            lock = await session.scalar(select(WarrantyEmailTemplateLock))

        self.assertFalse(result["matched"])
        self.assertEqual(result["template_key"], "miss-b")
        self.assertFalse(result["template_matched"])
        self.assertEqual(lock.email, "none@example.com")
        self.assertFalse(lock.matched)
        self.assertEqual(lock.template_key, "miss-b")

    async def test_existing_match_lock_switches_to_miss_when_email_removed(self):
        service = WarrantyService()

        async with self.Session() as session:
            entry = WarrantyEmailEntry(email="buyer@example.com", remaining_claims=1, last_redeem_code="CODE-A")
            session.add(entry)
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="match-a"):
                matched_result = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    warranty_code="CODE-A",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )

            await session.delete(entry)
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="miss-a"):
                missed_result = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    warranty_code="CODE-A",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )

            lock = await session.scalar(select(WarrantyEmailTemplateLock))

        self.assertTrue(matched_result["matched"])
        self.assertEqual(matched_result["template_key"], "match-a")
        self.assertFalse(missed_result["matched"])
        self.assertFalse(missed_result["template_matched"])
        self.assertEqual(missed_result["template_key"], "miss-a")
        self.assertFalse(lock.matched)
        self.assertEqual(lock.template_key, "miss-a")

    async def test_generated_redeem_code_is_created_once_and_reused(self):
        service = WarrantyService()

        async with self.Session() as session:
            entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=1,
                last_redeem_code="CODE-A",
                expires_at=get_now() + timedelta(days=2, hours=1),
            )
            session.add(entry)
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="match-a"):
                membership = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    warranty_code="CODE-A",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )

            api_result = {"success": True, "code": "TMW-GENERATED", "generated_at": get_now()}
            config = {
                "base_url": "https://sub2api.example.com",
                "admin_api_key": "admin-key",
                "subscription_group_id": 12,
                "code_prefix": "TMW",
                "configured": True,
            }
            with patch(
                "app.services.warranty.sub2api_warranty_redeem_client.create_subscription_code",
                new=AsyncMock(return_value=api_result),
            ) as mocked_create:
                first = await service.ensure_warranty_email_check_redeem_code(
                    session,
                    email="buyer@example.com",
                    user_id=42,
                    template_lock=membership["template_lock"],
                    warranty_entry=membership["selected_entry"],
                    sub2api_config=config,
                )
                second = await service.ensure_warranty_email_check_redeem_code(
                    session,
                    email="buyer@example.com",
                    user_id=42,
                    template_lock=membership["template_lock"],
                    warranty_entry=membership["selected_entry"],
                    sub2api_config=config,
                )

            lock = await session.scalar(select(WarrantyEmailTemplateLock))

        mocked_create.assert_awaited_once()
        self.assertTrue(first["success"])
        self.assertFalse(first["reused"])
        self.assertEqual(first["code"], "TMW-GENERATED")
        self.assertEqual(first["remaining_days"], 3)
        self.assertTrue(second["success"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["code"], "TMW-GENERATED")
        self.assertEqual(lock.generated_redeem_code, "TMW-GENERATED")
        self.assertEqual(lock.generated_redeem_code_remaining_days, 3)
        _, kwargs = mocked_create.call_args
        self.assertEqual(kwargs["validity_days"], 3)
        self.assertEqual(kwargs["sub2api_user_id"], 42)
        self.assertEqual(kwargs["group_id"], 12)


    async def test_generated_redeem_code_does_not_require_sub2api_user_id(self):
        service = WarrantyService()

        async with self.Session() as session:
            entry = WarrantyEmailEntry(
                email="buyer@example.com",
                remaining_claims=1,
                last_redeem_code="CODE-A",
                expires_at=get_now() + timedelta(days=29, hours=1),
            )
            session.add(entry)
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="match-a"):
                membership = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    warranty_code="CODE-A",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )

            config = {
                "base_url": "https://sub2api.example.com",
                "admin_api_key": "admin-key",
                "subscription_group_id": 12,
                "code_prefix": "TMW",
                "configured": True,
            }
            with patch(
                "app.services.warranty.sub2api_warranty_redeem_client.create_subscription_code",
                new=AsyncMock(return_value={"success": True, "code": "TMW-UNUSED", "generated_at": get_now()}),
            ) as mocked_create:
                result = await service.ensure_warranty_email_check_redeem_code(
                    session,
                    email="buyer@example.com",
                    user_id=None,
                    template_lock=membership["template_lock"],
                    warranty_entry=membership["selected_entry"],
                    sub2api_config=config,
                )

        mocked_create.assert_awaited_once()
        self.assertTrue(result["success"])
        self.assertEqual(result["code"], "TMW-UNUSED")
        self.assertEqual(result["remaining_days"], 30)

    async def test_membership_skips_code_generation_when_linked_team_is_usable(self):
        service = WarrantyService()

        async with self.Session() as session:
            active_team = Team(
                email="active-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-active",
                team_name="Active Team",
                status="active",
            )
            full_team = Team(
                email="full-owner@example.com",
                access_token_encrypted="dummy",
                account_id="acc-full",
                team_name="Full Team",
                status="full",
            )
            session.add_all([active_team, full_team])
            await session.flush()
            session.add_all([
                WarrantyEmailEntry(
                    email="active-buyer@example.com",
                    remaining_claims=1,
                    last_redeem_code="ACTIVE-CODE",
                    expires_at=get_now() + timedelta(days=2),
                    last_warranty_team_id=active_team.id,
                ),
                WarrantyEmailEntry(
                    email="full-buyer@example.com",
                    remaining_claims=1,
                    last_redeem_code="FULL-CODE",
                    expires_at=get_now() + timedelta(days=2),
                    last_warranty_team_id=full_team.id,
                ),
            ])
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="match-a"):
                active_result = await service.check_warranty_email_membership(
                    session,
                    "active-buyer@example.com",
                    warranty_code="ACTIVE-CODE",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )
                full_result = await service.check_warranty_email_membership(
                    session,
                    "full-buyer@example.com",
                    warranty_code="FULL-CODE",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )

        for result, status_label in [(active_result, "正常"), (full_result, "已满")]:
            self.assertTrue(result["matched"])
            self.assertTrue(result["skip_redeem_code_generation"])
            self.assertEqual(result["message"], "您所在的Team可以正常使用，无需提交质保")
            self.assertEqual(result["usable_linked_team"]["status_label"], status_label)

    async def test_email_with_no_redeem_code_returns_group_contact_message(self):
        service = WarrantyService()

        async with self.Session() as session:
            session.add(WarrantyEmailEntry(email="buyer@example.com", remaining_claims=1))
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="miss-a"):
                result = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    warranty_code="CODE-A",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )

        self.assertFalse(result["matched"])
        self.assertTrue(result["email_found"])
        self.assertFalse(result["email_has_redeem_code"])
        self.assertTrue(result["missing_redeem_code"])
        self.assertTrue(result["skip_redeem_code_generation"])
        self.assertEqual(result["message"], "请加入 QQ 群，联系群主处理。")
        self.assertEqual(result["template_key"], "miss-a")

    async def test_email_with_wrong_redeem_code_returns_fixed_error_message(self):
        service = WarrantyService()

        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=1,
                    last_redeem_code="CODE-A",
                )
            )
            await session.commit()

            with patch("app.services.warranty.secrets.choice", return_value="miss-a"):
                result = await service.check_warranty_email_membership(
                    session,
                    "buyer@example.com",
                    warranty_code="WRONG-CODE",
                    match_templates=[{"id": "match-a", "content": "<p>命中</p>"}],
                    miss_templates=[{"id": "miss-a", "content": "<p>未命中</p>"}],
                )

        self.assertFalse(result["matched"])
        self.assertTrue(result["email_found"])
        self.assertTrue(result["email_has_redeem_code"])
        self.assertFalse(result["missing_redeem_code"])
        self.assertTrue(result["wrong_redeem_code"])
        self.assertTrue(result["skip_redeem_code_generation"])
        self.assertEqual(result["message"], "您的质保兑换码错误")
        self.assertEqual(result["template_key"], "miss-a")





if __name__ == "__main__":
    unittest.main()
