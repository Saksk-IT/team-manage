import os
import tempfile
import unittest
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.database import Base
from app.models import WarrantyEmailTemplateLock
from app.routes.admin import code_generation_records_page
from app.utils.time_utils import get_now


class AdminCodeGenerationRecordsPageTests(unittest.IsolatedAsyncioTestCase):
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

    def _build_request(self, query_string: bytes = b"") -> Request:
        return Request({
            "type": "http",
            "method": "GET",
            "path": "/admin/code-generation-records",
            "query_string": query_string,
            "headers": [],
        })

    async def test_page_renders_statistics_for_generated_codes(self):
        now = get_now()
        async with self.Session() as session:
            session.add_all([
                WarrantyEmailTemplateLock(
                    email="buyer@example.com",
                    matched=True,
                    template_key="match-a",
                    generated_redeem_code="TMW-BUYER",
                    generated_redeem_code_remaining_days=30,
                    generated_redeem_code_generated_at=now,
                ),
                WarrantyEmailTemplateLock(
                    email="other@example.com",
                    matched=True,
                    template_key="match-a",
                    generated_redeem_code="TMW-OTHER",
                    generated_redeem_code_remaining_days=10,
                    generated_redeem_code_generated_at=now - timedelta(days=1),
                ),
            ])
            await session.commit()

            response = await code_generation_records_page(
                request=self._build_request(),
                email=None,
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn("生成总数", html)
        self.assertIn("涉及邮箱", html)
        self.assertIn("今日生成", html)
        self.assertIn("累计有效天数", html)
        self.assertIn("TMW-BUYER", html)
        self.assertIn("TMW-OTHER", html)
        self.assertIn(">40<", html)

    async def test_page_filters_generated_codes_by_email(self):
        now = get_now()
        async with self.Session() as session:
            session.add_all([
                WarrantyEmailTemplateLock(
                    email="buyer@example.com",
                    matched=True,
                    template_key="match-a",
                    generated_redeem_code="TMW-BUYER",
                    generated_redeem_code_remaining_days=30,
                    generated_redeem_code_generated_at=now,
                ),
                WarrantyEmailTemplateLock(
                    email="other@example.com",
                    matched=True,
                    template_key="match-a",
                    generated_redeem_code="TMW-OTHER",
                    generated_redeem_code_remaining_days=10,
                    generated_redeem_code_generated_at=now,
                ),
            ])
            await session.commit()

            response = await code_generation_records_page(
                request=self._build_request(b"email=buyer%40example.com"),
                email="buyer@example.com",
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn('value="buyer@example.com"', html)
        self.assertIn("TMW-BUYER", html)
        self.assertNotIn("TMW-OTHER", html)
        self.assertIn(">30<", html)


if __name__ == "__main__":
    unittest.main()
