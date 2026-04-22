import json
import os
import tempfile
import unittest
from datetime import timedelta

from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import WarrantyEmailEntry
from app.routes.admin import (
    WarrantyEmailSaveRequest,
    delete_warranty_email,
    save_warranty_email,
    warranty_emails_page,
)
from app.utils.time_utils import get_now


class AdminWarrantyEmailManagementTests(unittest.IsolatedAsyncioTestCase):
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

    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/admin/warranty-emails", "headers": []})

    async def test_warranty_emails_page_renders_entry(self):
        async with self.Session() as session:
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=2,
                    expires_at=get_now() + timedelta(days=5),
                    source="manual",
                    last_redeem_code="CODE-123"
                )
            )
            await session.commit()

            response = await warranty_emails_page(
                request=self._build_request(),
                search=None,
                db=session,
                current_user={"username": "admin"}
            )

        html = response.body.decode("utf-8")
        self.assertIn("质保邮箱列表", html)
        self.assertIn("buyer@example.com", html)
        self.assertIn("CODE-123", html)
        self.assertIn('id="warrantyRemainingDays" class="form-control" min="0" value="30"', html)
        self.assertIn('id="warrantyRemainingClaims" class="form-control" min="0" value="10" required', html)
        self.assertIn("remainingDaysInput.value = entry.remaining_days ?? remainingDaysInput.defaultValue;", html)
        self.assertIn("remainingClaimsInput.value = entry.remaining_claims ?? remainingClaimsInput.defaultValue;", html)

    async def test_warranty_emails_page_supports_search_by_redeem_code(self):
        async with self.Session() as session:
            session.add_all(
                [
                    WarrantyEmailEntry(
                        email="buyer@example.com",
                        remaining_claims=2,
                        expires_at=get_now() + timedelta(days=5),
                        source="manual",
                        last_redeem_code="CODE-123"
                    ),
                    WarrantyEmailEntry(
                        email="other@example.com",
                        remaining_claims=1,
                        expires_at=get_now() + timedelta(days=3),
                        source="manual",
                        last_redeem_code="OTHER-456"
                    ),
                ]
            )
            await session.commit()

            response = await warranty_emails_page(
                request=self._build_request(),
                search="CODE-123",
                db=session,
                current_user={"username": "admin"}
            )

        html = response.body.decode("utf-8")
        self.assertIn("buyer@example.com", html)
        self.assertNotIn("other@example.com", html)
        self.assertIn('placeholder="搜索邮箱或兑换码"', html)

    async def test_save_and_delete_warranty_email(self):
        async with self.Session() as session:
            save_response = await save_warranty_email(
                payload=WarrantyEmailSaveRequest(
                    email="buyer@example.com",
                    remaining_days=5,
                    remaining_claims=2
                ),
                db=session,
                current_user={"username": "admin"}
            )

            save_payload = json.loads(save_response.body.decode("utf-8"))
            entry_id = save_payload["entry"]["id"]

            delete_response = await delete_warranty_email(
                entry_id=entry_id,
                db=session,
                current_user={"username": "admin"}
            )

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_payload["success"])
        self.assertEqual(delete_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
