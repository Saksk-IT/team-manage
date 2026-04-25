import json
import os
import re
import tempfile
import unittest
from datetime import timedelta

from starlette.requests import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, WarrantyEmailEntry
from app.routes.admin import (
    BulkWarrantyCodeQuotaUpdateRequest,
    bulk_update_warranty_code_quota,
    codes_list_page,
)
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
        self.assertNotIn("可重复使用", html)
        self.assertNotIn("如果是质保兑换码，在质保期内，如果加入的 Team 被封号，可以重复使用", html)
        self.assertIn("兑换成功后会把使用邮箱加入质保邮箱列表", html)
        self.assertIn("默认 10 次质保次数", html)

    async def test_codes_page_accepts_empty_multi_filter_fields(self):
        async with self.Session() as session:
            response = await codes_list_page(
                request=self._build_request(),
                page=1,
                per_page=50,
                search="",
                status_filter="",
                team_id="",
                code_type="",
                created_from="",
                created_to="",
                warranty_days="",
                remaining_days_min="",
                remaining_days_max="",
                remaining_claims_min="",
                remaining_claims_max="",
                db=session,
                current_user={"username": "admin"},
            )

        html = response.body.decode("utf-8")
        self.assertIn('name="code_type"', html)
        self.assertIn('name="created_from"', html)
        self.assertIn('name="remaining_claims_max"', html)
        self.assertIn('id="bulkWarrantyQuotaModal"', html)
        self.assertIn('/admin/codes/bulk-warranty-quota-update', html)

    async def test_bulk_warranty_code_quota_update_can_use_current_filters(self):
        async with self.Session() as session:
            session.add_all([
                RedemptionCode(
                    code="FILTER-WARRANTY-001",
                    status="unused",
                    has_warranty=True,
                    warranty_days=30,
                    warranty_claims=10,
                ),
                RedemptionCode(
                    code="FILTER-NORMAL-001",
                    status="unused",
                    has_warranty=False,
                    warranty_days=30,
                    warranty_claims=10,
                ),
            ])
            await session.commit()

            response = await bulk_update_warranty_code_quota(
                update_data=BulkWarrantyCodeQuotaUpdateRequest(
                    codes=[],
                    status_filter="unused",
                    code_type="warranty",
                    remaining_days=8,
                    remaining_claims=2,
                ),
                db=session,
                current_user={"username": "admin"},
            )

            warranty_code = await session.get(RedemptionCode, 1)
            normal_code = await session.get(RedemptionCode, 2)

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["success"])
        self.assertEqual(payload["updated_count"], 1)
        self.assertEqual(warranty_code.warranty_days, 8)
        self.assertEqual(warranty_code.warranty_claims, 2)
        self.assertEqual(normal_code.warranty_days, 30)
        self.assertEqual(normal_code.warranty_claims, 10)


if __name__ == "__main__":
    unittest.main()
