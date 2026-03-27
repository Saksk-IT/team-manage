import os
import tempfile
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import RedemptionCode, RedemptionRecord, Setting, Team
from app.services.settings import settings_service
from app.services.team import TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY
from app.services.warranty import WarrantyService


class WarrantyFakeSuccessValidationTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_base_data(self, session):
        ordinary_team = Team(
            email="ordinary-owner@example.com",
            access_token_encrypted="dummy",
            account_id="acc-ordinary",
            team_type=TEAM_TYPE_STANDARD,
            team_name="Ordinary Team",
            status="active",
            current_members=2,
            max_members=5
        )
        warranty_team = Team(
            email="warranty-owner@example.com",
            access_token_encrypted="dummy",
            account_id="acc-warranty",
            team_type=TEAM_TYPE_WARRANTY,
            team_name="Warranty Team",
            status="active",
            current_members=1,
            max_members=5
        )
        session.add_all([
            ordinary_team,
            warranty_team,
            Setting(key=settings_service.WARRANTY_USAGE_LIMIT_SUPER_CODE_KEY, value="USAGE-CODE-1234"),
            Setting(key=settings_service.WARRANTY_USAGE_LIMIT_MAX_USES_KEY, value="2"),
        ])
        await session.flush()
        return ordinary_team

    async def test_validate_warranty_claim_input_success(self):
        async with self.Session() as session:
            ordinary_team = await self._seed_base_data(session)
            session.add(
                RedemptionCode(
                    code="CODE-VALID",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                ordinary_code="CODE-VALID",
                email="buyer@example.com",
                super_code="usage-code-1234"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["ordinary_code"], "CODE-VALID")
        self.assertEqual(result["normalized_email"], "buyer@example.com")

    async def test_validate_warranty_claim_input_rejects_missing_code(self):
        async with self.Session() as session:
            await self._seed_base_data(session)
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                ordinary_code="CODE-MISSING",
                email="buyer@example.com",
                super_code="usage-code-1234"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "普通兑换码不存在")

    async def test_validate_warranty_claim_input_rejects_mismatched_email(self):
        async with self.Session() as session:
            ordinary_team = await self._seed_base_data(session)
            session.add(
                RedemptionCode(
                    code="CODE-MISMATCH",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                ordinary_code="CODE-MISMATCH",
                email="other@example.com",
                super_code="usage-code-1234"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "邮箱与普通兑换码不匹配")

    async def test_validate_warranty_claim_input_rejects_invalid_super_code(self):
        async with self.Session() as session:
            ordinary_team = await self._seed_base_data(session)
            session.add(
                RedemptionCode(
                    code="CODE-SUPER",
                    status="used",
                    bound_team_id=ordinary_team.id,
                    used_by_email="buyer@example.com",
                    used_team_id=ordinary_team.id
                )
            )
            await session.commit()

            result = await WarrantyService().validate_warranty_claim_input(
                db_session=session,
                ordinary_code="CODE-SUPER",
                email="buyer@example.com",
                super_code="INVALID-SUPER-CODE"
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "超级兑换码错误或未启用")


if __name__ == "__main__":
    unittest.main()
