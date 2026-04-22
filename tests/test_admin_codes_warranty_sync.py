import os
import re
import tempfile
import unittest
from datetime import timedelta

from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, WarrantyEmailEntry
from app.routes.admin import codes_list_page
from app.utils.time_utils import get_now


class AdminCodesWarrantySyncTests(unittest.IsolatedAsyncioTestCase):
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
        return Request({"type": "http", "method": "GET", "path": "/admin/codes", "headers": []})

    async def test_codes_page_renders_warranty_type_and_synced_remaining_values(self):
        async with self.Session() as session:
            session.add(
                RedemptionCode(
                    code="WARRANTY-CODE-001",
                    status="used",
                    has_warranty=True,
                    warranty_days=30,
                    used_by_email="buyer@example.com",
                    used_at=get_now(),
                )
            )
            session.add(
                WarrantyEmailEntry(
                    email="buyer@example.com",
                    remaining_claims=8,
                    expires_at=get_now() + timedelta(days=12),
                    source="auto_redeem",
                    last_redeem_code="WARRANTY-CODE-001",
                )
            )
            await session.commit()

            response = await codes_list_page(
                request=self._build_request(),
                page=1,
                per_page=50,
                search=None,
                status_filter=None,
                team_id=None,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("WARRANTY-CODE-001", html)
        self.assertIn("质保兑换码", html)
        self.assertIn("剩余天数", html)
        self.assertIn("剩余次数", html)
        self.assertRegex(html, r">\s*12\s*<")
        self.assertRegex(html, r">\s*8\s*<")


if __name__ == "__main__":
    unittest.main()
