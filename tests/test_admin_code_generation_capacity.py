import json
import os
import tempfile
import unittest

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, Team
from app.routes.admin import CodeGenerateRequest, generate_codes


class AdminCodeGenerationCapacityTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_generate_rejects_when_unused_codes_would_exceed_available_seats(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="capacity-owner@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-capacity",
                    status="active",
                    current_members=4,
                    max_members=9,
                )
            )
            session.add_all([
                RedemptionCode(code=f"UNUSED-CODE-{index:03d}", status="unused")
                for index in range(1, 6)
            ])
            await session.commit()

            response = await generate_codes(
                generate_data=CodeGenerateRequest(type="single"),
                db=session,
                current_user={"username": "admin"},
            )

            total_codes = await session.scalar(select(func.count(RedemptionCode.id)))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertIn("可用席位不足", payload["error"])
        self.assertEqual(total_codes, 5)

    async def test_generate_persists_warranty_claims_and_seconds_when_capacity_allows(self):
        async with self.Session() as session:
            session.add(
                Team(
                    email="warranty-owner@example.com",
                    access_token_encrypted="dummy",
                    account_id="acc-warranty-capacity",
                    status="active",
                    current_members=1,
                    max_members=2,
                )
            )
            await session.commit()

            response = await generate_codes(
                generate_data=CodeGenerateRequest(
                    type="single",
                    code="WARRANTY-CAP-001",
                    has_warranty=True,
                    warranty_days=8,
                    warranty_seconds=7 * 86400 + 3600,
                    warranty_claims=15,
                ),
                db=session,
                current_user={"username": "admin"},
            )

            code = await session.scalar(
                select(RedemptionCode).where(RedemptionCode.code == "WARRANTY-CAP-001")
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertIsNotNone(code)
        self.assertTrue(code.has_warranty)
        self.assertEqual(code.warranty_days, 8)
        self.assertEqual(code.warranty_seconds, 7 * 86400 + 3600)
        self.assertEqual(code.warranty_claims, 15)


if __name__ == "__main__":
    unittest.main()
