"""
兑换码管理服务
用于管理兑换码的生成、验证、使用和查询
"""
import logging
import secrets
import string
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy import select, update, delete, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import RedemptionCode, RedemptionRecord, Team, WarrantyEmailEntry
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class RedemptionService:
    """兑换码管理服务类"""

    def __init__(self):
        """初始化兑换码管理服务"""
        pass

    def _usage_record_exists_clause(self):
        """返回与 RedemptionCode 相关的使用记录存在性条件。"""
        return select(RedemptionRecord.id).where(
            RedemptionRecord.code == RedemptionCode.code
        ).exists()

    def _effective_code_status(self, stored_status: Optional[str], has_usage_record: bool) -> str:
        """兑换码列表展示状态：使用记录存在时优先视为已使用。"""
        status = (stored_status or "unused").strip() or "unused"
        if has_usage_record and status != "warranty_active":
            return "used"
        return status

    async def _get_usage_record_code_set(
        self,
        db_session: AsyncSession,
        codes: List[str],
    ) -> set:
        """查询已有使用记录的兑换码集合。"""
        normalized_codes = list(dict.fromkeys([
            (code or "").strip()
            for code in codes
            if (code or "").strip()
        ]))
        if not normalized_codes:
            return set()

        stmt = select(RedemptionRecord.code).where(
            RedemptionRecord.code.in_(normalized_codes)
        ).distinct()
        result = await db_session.execute(stmt)
        return set(result.scalars().all())

    async def _get_latest_usage_record_map(
        self,
        db_session: AsyncSession,
        codes: List[str],
    ) -> Dict[str, RedemptionRecord]:
        """按兑换码取最新使用记录。"""
        normalized_codes = list(dict.fromkeys([
            (code or "").strip()
            for code in codes
            if (code or "").strip()
        ]))
        if not normalized_codes:
            return {}

        stmt = (
            select(RedemptionRecord)
            .where(RedemptionRecord.code.in_(normalized_codes))
            .order_by(
                RedemptionRecord.code.asc(),
                RedemptionRecord.redeemed_at.desc(),
                RedemptionRecord.id.desc(),
            )
        )
        result = await db_session.execute(stmt)
        latest_record_map = {}
        for record in result.scalars().all():
            latest_record_map.setdefault(record.code, record)
        return latest_record_map

    def _generate_random_code(self, length: int = 16) -> str:
        """
        生成随机兑换码

        Args:
            length: 兑换码长度

        Returns:
            随机兑换码字符串
        """
        # 使用大写字母和数字,排除容易混淆的字符 (0, O, I, 1)
        alphabet = string.ascii_uppercase + string.digits
        alphabet = alphabet.replace('0', '').replace('O', '').replace('I', '').replace('1', '')

        # 生成随机码
        code = ''.join(secrets.choice(alphabet) for _ in range(length))

        # 格式化为 XXXX-XXXX-XXXX-XXXX
        if length == 16:
            code = f"{code[0:4]}-{code[4:8]}-{code[8:12]}-{code[12:16]}"

        return code

    async def _ensure_unique_code(
        self,
        db_session: AsyncSession,
        reserved_codes: Optional[set] = None
    ) -> Optional[str]:
        """
        生成一个唯一兑换码
        """
        reserved_codes = reserved_codes or set()
        max_attempts = 10

        for _ in range(max_attempts):
            code = self._generate_random_code()
            if code in reserved_codes:
                continue

            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            existing = result.scalar_one_or_none()

            if not existing:
                return code

        return None

    async def generate_code_single(
        self,
        db_session: AsyncSession,
        code: Optional[str] = None,
        expires_days: Optional[int] = None,
        has_warranty: bool = False,
        warranty_days: int = 30,
        warranty_claims: int = 10,
        bound_team_id: Optional[int] = None,
        commit: bool = True
    ) -> Dict[str, Any]:
        """
        生成单个兑换码

        Args:
            db_session: 数据库会话
            code: 自定义兑换码 (可选,如果不提供则自动生成)
            expires_days: 有效期天数 (可选,如果不提供则永久有效)
            has_warranty: 是否为质保兑换码 (默认 False)

        Returns:
            结果字典,包含 success, code, message, error
        """
        try:
            # 1. 生成或使用自定义兑换码
            if not code:
                code = await self._ensure_unique_code(db_session)
                if not code:
                    return {
                        "success": False,
                        "code": None,
                        "message": None,
                        "error": "生成唯一兑换码失败,请重试"
                    }
            else:
                # 检查自定义兑换码是否已存在
                stmt = select(RedemptionCode).where(RedemptionCode.code == code)
                result = await db_session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    return {
                        "success": False,
                        "code": None,
                        "message": None,
                        "error": f"兑换码 {code} 已存在"
                    }

            # 2. 计算过期时间
            expires_at = None
            if expires_days:
                expires_at = get_now() + timedelta(days=expires_days)

            # 3. 创建兑换码记录
            redemption_code = RedemptionCode(
                code=code,
                status="unused",
                expires_at=expires_at,
                bound_team_id=bound_team_id,
                has_warranty=has_warranty,
                warranty_days=warranty_days,
                warranty_claims=warranty_claims
            )

            db_session.add(redemption_code)
            if commit:
                await db_session.commit()
            else:
                await db_session.flush()

            logger.info(f"生成兑换码成功: {code}")

            return {
                "success": True,
                "code": code,
                "bound_team_id": bound_team_id,
                "message": f"兑换码生成成功: {code}",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"生成兑换码失败: {e}")
            return {
                "success": False,
                "code": None,
                "message": None,
                "error": f"生成兑换码失败: {str(e)}"
            }

    async def generate_code_batch(
        self,
        db_session: AsyncSession,
        count: int,
        expires_days: Optional[int] = None,
        has_warranty: bool = False,
        warranty_days: int = 30,
        warranty_claims: int = 10,
        bound_team_id: Optional[int] = None,
        commit: bool = True
    ) -> Dict[str, Any]:
        """
        批量生成兑换码

        Args:
            db_session: 数据库会话
            count: 生成数量
            expires_days: 有效期天数 (可选)
            has_warranty: 是否为质保兑换码 (默认 False)

        Returns:
            结果字典,包含 success, codes, total, message, error
        """
        try:
            if count <= 0 or count > 1000:
                return {
                    "success": False,
                    "codes": [],
                    "total": 0,
                    "message": None,
                    "error": "生成数量必须在 1-1000 之间"
                }

            # 计算过期时间
            expires_at = None
            if expires_days:
                expires_at = get_now() + timedelta(days=expires_days)

            # 批量生成兑换码
            codes = []
            for i in range(count):
                code = await self._ensure_unique_code(db_session, reserved_codes=set(codes))
                if not code:
                    logger.warning(f"生成第 {i+1} 个兑换码失败")
                    continue
                codes.append(code)

            # 批量插入数据库
            for code in codes:
                redemption_code = RedemptionCode(
                    code=code,
                    status="unused",
                    expires_at=expires_at,
                    bound_team_id=bound_team_id,
                    has_warranty=has_warranty,
                    warranty_days=warranty_days,
                    warranty_claims=warranty_claims
                )
                db_session.add(redemption_code)

            if commit:
                await db_session.commit()
            else:
                await db_session.flush()

            logger.info(f"批量生成兑换码成功: {len(codes)} 个")

            return {
                "success": True,
                "codes": codes,
                "total": len(codes),
                "bound_team_id": bound_team_id,
                "message": f"成功生成 {len(codes)} 个兑换码",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"批量生成兑换码失败: {e}")
            return {
                "success": False,
                "codes": [],
                "total": 0,
                "message": None,
                "error": f"批量生成兑换码失败: {str(e)}"
            }

    async def validate_code(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        验证兑换码

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, valid, reason, redemption_code, error
        """
        try:
            # 1. 查询兑换码
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": True,
                    "valid": False,
                    "reason": "兑换码不存在",
                    "redemption_code": None,
                    "error": None
                }

            # 2. 检查状态
            if redemption_code.status != "unused":
                if redemption_code.status in ["used", "warranty_active"]:
                    reason = "兑换码已被使用，不可用"
                elif redemption_code.status == "processing":
                    reason = "兑换码正在处理中，请稍后查看结果"
                elif redemption_code.status == "expired":
                    reason = "兑换码已过期"
                else:
                    reason = f"兑换码状态无效: {redemption_code.status}"
                return {
                    "success": True,
                    "valid": False,
                    "reason": reason,
                    "redemption_code": None,
                    "error": None
                }

            # 3. 检查是否过期 (仅针对未使用的兑换码执行首次激活截止时间检查)
            if redemption_code.status == "unused" and redemption_code.expires_at:
                if redemption_code.expires_at < get_now():
                    # 更新状态为 expired
                    redemption_code.status = "expired"
                    # 不在服务层内部 commit，让调用方决定事务边界
                    # await db_session.commit() 

                    return {
                        "success": True,
                        "valid": False,
                        "reason": "兑换码已过期 (超过首次兑换截止时间)",
                        "redemption_code": None,
                        "error": None
                    }

            # 4. 验证通过
            return {
                "success": True,
                "valid": True,
                "reason": "兑换码有效",
                "redemption_code": {
                    "id": redemption_code.id,
                    "code": redemption_code.code,
                    "status": redemption_code.status,
                    "bound_team_id": redemption_code.bound_team_id,
                    "expires_at": redemption_code.expires_at.isoformat() if redemption_code.expires_at else None,
                    "created_at": redemption_code.created_at.isoformat() if redemption_code.created_at else None
                },
                "error": None
            }

        except Exception as e:
            logger.error(f"验证兑换码失败: {e}")
            return {
                "success": False,
                "valid": False,
                "reason": None,
                "redemption_code": None,
                "error": f"验证兑换码失败: {str(e)}"
            }

    async def use_code(
        self,
        code: str,
        email: str,
        team_id: int,
        account_id: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        使用兑换码

        Args:
            code: 兑换码
            email: 使用者邮箱
            team_id: Team ID
            account_id: Account ID
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 1. 验证兑换码
            validate_result = await self.validate_code(code, db_session)

            if not validate_result["success"]:
                return {
                    "success": False,
                    "message": None,
                    "error": validate_result["error"]
                }

            if not validate_result["valid"]:
                return {
                    "success": False,
                    "message": None,
                    "error": validate_result["reason"]
                }

            # 2. 更新兑换码状态
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            redemption_code.status = "used"
            redemption_code.used_by_email = email
            redemption_code.used_team_id = team_id
            redemption_code.used_at = get_now()

            # 3. 创建使用记录
            redemption_record = RedemptionRecord(
                email=email,
                code=code,
                team_id=team_id,
                account_id=account_id
            )

            db_session.add(redemption_record)
            await db_session.commit()

            logger.info(f"使用兑换码成功: {code} -> {email}")

            return {
                "success": True,
                "message": "兑换码使用成功",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"使用兑换码失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"使用兑换码失败: {str(e)}"
            }

    async def get_all_codes(
        self,
        db_session: AsyncSession,
        page: int = 1,
        per_page: int = 100,
        search: Optional[str] = None,
        status: Optional[str] = None,
        selected_codes: Optional[List[str]] = None,
        bound_team_id: Optional[int] = None,
        bound_team_ids: Optional[List[int]] = None,
        code_type: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        warranty_days: Optional[int] = None,
        remaining_days_min: Optional[int] = None,
        remaining_days_max: Optional[int] = None,
        remaining_claims_min: Optional[int] = None,
        remaining_claims_max: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        获取所有兑换码

        Args:
            db_session: 数据库会话
            page: 页码
            per_page: 每页数量
            search: 搜索关键词 (兑换码或邮箱)
            status: 状态筛选
            selected_codes: 指定导出的兑换码列表
            bound_team_id: 绑定的单个 Team ID
            bound_team_ids: 绑定的多个 Team ID 列表
            code_type: 兑换码类型筛选 (standard/warranty)
            created_from: 创建时间起始
            created_to: 创建时间结束
            warranty_days: 质保时长筛选
            remaining_days_min: 剩余天数最小值
            remaining_days_max: 剩余天数最大值
            remaining_claims_min: 剩余次数最小值
            remaining_claims_max: 剩余次数最大值

        Returns:
            结果字典,包含 success, codes, total, total_pages, current_page, error
        """
        try:
            # 1. 构建基础查询
            count_stmt = select(func.count(RedemptionCode.id)).select_from(RedemptionCode)
            stmt = select(RedemptionCode).select_from(RedemptionCode).order_by(RedemptionCode.created_at.desc())

            # 2. 如果提供了筛选条件,添加过滤条件
            filters = []
            has_remaining_day_filter = (
                remaining_days_min is not None or remaining_days_max is not None
            )
            has_remaining_claim_filter = (
                remaining_claims_min is not None or remaining_claims_max is not None
            )
            needs_warranty_entry_filter = has_remaining_day_filter or has_remaining_claim_filter
            if needs_warranty_entry_filter:
                warranty_entry_join = (
                    WarrantyEmailEntry.email == func.lower(func.trim(RedemptionCode.used_by_email))
                )
                count_stmt = count_stmt.outerjoin(WarrantyEmailEntry, warranty_entry_join)
                stmt = stmt.outerjoin(WarrantyEmailEntry, warranty_entry_join)
                filters.append(RedemptionCode.has_warranty.is_(True))

            if search:
                usage_record_email_exists = select(RedemptionRecord.id).where(and_(
                    RedemptionRecord.code == RedemptionCode.code,
                    RedemptionRecord.email.ilike(f"%{search}%"),
                )).exists()
                filters.append(or_(
                    RedemptionCode.code.ilike(f"%{search}%"),
                    RedemptionCode.used_by_email.ilike(f"%{search}%"),
                    usage_record_email_exists,
                ))

            if selected_codes:
                filters.append(RedemptionCode.code.in_(selected_codes))

            if bound_team_ids:
                filters.append(RedemptionCode.bound_team_id.in_(bound_team_ids))
            elif bound_team_id:
                filters.append(RedemptionCode.bound_team_id == bound_team_id)

            if status:
                if status == 'used':
                    filters.append(or_(
                        self._usage_record_exists_clause(),
                        RedemptionCode.status.in_(['used', 'warranty_active']),
                    ))
                elif status == 'unused':
                    filters.append(and_(
                        RedemptionCode.status == "unused",
                        ~self._usage_record_exists_clause(),
                    ))
                elif status == 'expired':
                    filters.append(and_(
                        RedemptionCode.status == "expired",
                        ~self._usage_record_exists_clause(),
                    ))
                else:
                    filters.append(RedemptionCode.status == status)

            normalized_code_type = (code_type or "").strip().lower()
            if normalized_code_type == "standard":
                filters.append(or_(
                    RedemptionCode.has_warranty.is_(False),
                    RedemptionCode.has_warranty.is_(None)
                ))
            elif normalized_code_type == "warranty":
                filters.append(RedemptionCode.has_warranty.is_(True))
            elif normalized_code_type:
                return {
                    "success": False,
                    "codes": [],
                    "total": 0,
                    "error": "无效的兑换码类型筛选"
                }

            if created_from:
                filters.append(RedemptionCode.created_at >= created_from)

            if created_to:
                filters.append(RedemptionCode.created_at <= created_to)

            if warranty_days is not None:
                filters.append(RedemptionCode.has_warranty.is_(True))
                filters.append(RedemptionCode.warranty_days == warranty_days)

            used_warranty_remaining_filters = []
            unused_warranty_remaining_filters = []
            if needs_warranty_entry_filter:
                used_warranty_remaining_filters.extend([
                    RedemptionCode.has_warranty.is_(True),
                    WarrantyEmailEntry.id.isnot(None),
                ])
                unused_warranty_remaining_filters.extend([
                    RedemptionCode.has_warranty.is_(True),
                    RedemptionCode.status == "unused",
                    ~self._usage_record_exists_clause(),
                ])

            if has_remaining_day_filter:
                now = get_now()
                used_warranty_remaining_filters.append(WarrantyEmailEntry.expires_at.isnot(None))
                if remaining_days_min is not None and remaining_days_min > 0:
                    used_warranty_remaining_filters.append(
                        WarrantyEmailEntry.expires_at > now + timedelta(days=remaining_days_min - 1)
                    )
                    unused_warranty_remaining_filters.append(
                        RedemptionCode.warranty_days >= remaining_days_min
                    )
                elif remaining_days_min is not None:
                    unused_warranty_remaining_filters.append(
                        RedemptionCode.warranty_days >= remaining_days_min
                    )
                if remaining_days_max is not None:
                    used_warranty_remaining_filters.append(
                        WarrantyEmailEntry.expires_at <= now + timedelta(days=remaining_days_max)
                    )
                    unused_warranty_remaining_filters.append(
                        RedemptionCode.warranty_days <= remaining_days_max
                    )

            if remaining_claims_min is not None:
                used_warranty_remaining_filters.append(WarrantyEmailEntry.remaining_claims >= remaining_claims_min)
                unused_warranty_remaining_filters.append(RedemptionCode.warranty_claims >= remaining_claims_min)

            if remaining_claims_max is not None:
                used_warranty_remaining_filters.append(WarrantyEmailEntry.remaining_claims <= remaining_claims_max)
                unused_warranty_remaining_filters.append(RedemptionCode.warranty_claims <= remaining_claims_max)

            if needs_warranty_entry_filter:
                filters.append(or_(
                    and_(*used_warranty_remaining_filters),
                    and_(*unused_warranty_remaining_filters),
                ))
            
            if filters:
                count_stmt = count_stmt.where(and_(*filters))
                stmt = stmt.where(and_(*filters))

            # 3. 获取总数
            count_result = await db_session.execute(count_stmt)
            total = count_result.scalar() or 0

            # 4. 计算分页
            import math
            total_pages = math.ceil(total / per_page) if total > 0 else 1
            if page < 1:
                page = 1
            if page > total_pages and total_pages > 0:
                page = total_pages
            
            offset = (page - 1) * per_page

            # 5. 查询分页数据
            stmt = stmt.limit(per_page).offset(offset)
            result = await db_session.execute(stmt)
            codes = result.scalars().all()
            latest_usage_record_map = await self._get_latest_usage_record_map(
                db_session,
                [code.code for code in codes],
            )

            bound_team_ids = {code.bound_team_id for code in codes if code.bound_team_id}
            team_map = {}
            if bound_team_ids:
                team_stmt = select(Team).where(Team.id.in_(bound_team_ids))
                team_result = await db_session.execute(team_stmt)
                team_map = {team.id: team for team in team_result.scalars().all()}

            warranty_entry_map = {}
            used_emails = set()
            for code in codes:
                latest_record = latest_usage_record_map.get(code.code)
                used_email = latest_record.email if latest_record else code.used_by_email
                normalized_email = (used_email or "").strip().lower()
                if normalized_email:
                    used_emails.add(normalized_email)
            if used_emails:
                warranty_stmt = select(WarrantyEmailEntry).where(
                    WarrantyEmailEntry.email.in_(used_emails)
                )
                warranty_result = await db_session.execute(warranty_stmt)
                warranty_entry_map = {
                    entry.email: entry for entry in warranty_result.scalars().all()
                }

            from app.services.warranty import warranty_service

            # 构建返回数据
            code_list = []
            for code in codes:
                bound_team = team_map.get(code.bound_team_id)
                latest_record = latest_usage_record_map.get(code.code)
                display_status = self._effective_code_status(
                    code.status,
                    latest_record is not None,
                )
                display_used_email = latest_record.email if latest_record else code.used_by_email
                display_used_team_id = latest_record.team_id if latest_record else code.used_team_id
                display_used_at = latest_record.redeemed_at if latest_record else code.used_at
                normalized_used_email = (display_used_email or "").strip().lower()
                warranty_entry = warranty_entry_map.get(normalized_used_email)
                serialized_warranty_entry = (
                    warranty_service.serialize_warranty_email_entry(warranty_entry)
                    if warranty_entry and code.has_warranty
                    else {}
                )
                warranty_remaining_days = serialized_warranty_entry.get("remaining_days")
                warranty_remaining_claims = serialized_warranty_entry.get("remaining_claims")
                if code.has_warranty and not normalized_used_email:
                    warranty_remaining_days = code.warranty_days
                    warranty_remaining_claims = code.warranty_claims
                code_list.append({
                    "id": code.id,
                    "code": code.code,
                    "status": display_status,
                    "created_at": code.created_at.isoformat() if code.created_at else None,
                    "expires_at": code.expires_at.isoformat() if code.expires_at else None,
                    "bound_team_id": code.bound_team_id,
                    "bound_team_name": bound_team.team_name if bound_team else None,
                    "bound_team_email": bound_team.email if bound_team else None,
                    "bound_account_id": bound_team.account_id if bound_team else None,
                    "used_by_email": display_used_email,
                    "used_team_id": display_used_team_id,
                    "used_at": display_used_at.isoformat() if display_used_at else None,
                    "has_warranty": code.has_warranty,
                    "warranty_days": code.warranty_days,
                    "warranty_claims": code.warranty_claims,
                    "warranty_expires_at": code.warranty_expires_at.isoformat() if code.warranty_expires_at else None,
                    "warranty_remaining_days": warranty_remaining_days,
                    "warranty_remaining_claims": warranty_remaining_claims,
                })

            logger.info(f"获取所有兑换码成功: 第 {page} 页, 共 {len(code_list)} 个 / 总数 {total}")

            return {
                "success": True,
                "codes": code_list,
                "total": total,
                "total_pages": total_pages,
                "current_page": page,
                "error": None
            }

        except Exception as e:
            logger.error(f"获取所有兑换码失败: {e}")
            return {
                "success": False,
                "codes": [],
                "total": 0,
                "error": f"获取所有兑换码失败: {str(e)}"
            }

    async def get_unused_count(
        self,
        db_session: AsyncSession
    ) -> int:
        """
        获取未使用的兑换码数量
        """
        try:
            stmt = select(func.count(RedemptionCode.id)).where(and_(
                RedemptionCode.status == "unused",
                ~self._usage_record_exists_clause(),
            ))
            result = await db_session.execute(stmt)
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"获取未使用兑换码数量失败: {e}")
            return 0

    async def get_code_by_code(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        根据兑换码查询

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, code_info, error
        """
        try:
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": False,
                    "code_info": None,
                    "error": f"兑换码 {code} 不存在"
                }

            code_info = {
                "id": redemption_code.id,
                "code": redemption_code.code,
                "status": redemption_code.status,
                "created_at": redemption_code.created_at.isoformat() if redemption_code.created_at else None,
                "expires_at": redemption_code.expires_at.isoformat() if redemption_code.expires_at else None,
                "bound_team_id": redemption_code.bound_team_id,
                "used_by_email": redemption_code.used_by_email,
                "used_team_id": redemption_code.used_team_id,
                "used_at": redemption_code.used_at.isoformat() if redemption_code.used_at else None
            }

            return {
                "success": True,
                "code_info": code_info,
                "error": None
            }

        except Exception as e:
            logger.error(f"查询兑换码失败: {e}")
            return {
                "success": False,
                "code_info": None,
                "error": f"查询兑换码失败: {str(e)}"
            }

    async def lookup_code_binding_email(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        根据兑换码查询当前绑定邮箱信息（前台公开查询使用）。

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典，包含 success、found、bound、used_by_email、status、used_at、message、error
        """
        normalized_code = (code or "").strip()
        if not normalized_code:
            return {
                "success": False,
                "found": False,
                "bound": False,
                "used_by_email": None,
                "status": None,
                "used_at": None,
                "message": None,
                "error": "兑换码不能为空"
            }

        try:
            stmt = select(RedemptionCode).where(RedemptionCode.code == normalized_code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": True,
                    "found": False,
                    "bound": False,
                    "used_by_email": None,
                    "status": None,
                    "used_at": None,
                    "message": "未找到该兑换码",
                    "error": None
                }

            used_by_email = (redemption_code.used_by_email or "").strip() or None
            bound = bool(used_by_email)

            if bound:
                message = "已查询到该兑换码绑定邮箱"
            elif redemption_code.status == "unused":
                message = "该兑换码当前未绑定邮箱"
            elif redemption_code.status == "expired":
                message = "该兑换码已过期，当前未绑定邮箱"
            else:
                message = "该兑换码暂无可展示的绑定邮箱信息"

            return {
                "success": True,
                "found": True,
                "bound": bound,
                "used_by_email": used_by_email,
                "status": redemption_code.status,
                "used_at": redemption_code.used_at.isoformat() if redemption_code.used_at else None,
                "message": message,
                "error": None
            }

        except Exception as e:
            logger.error(f"查询兑换码绑定邮箱失败: {e}")
            return {
                "success": False,
                "found": False,
                "bound": False,
                "used_by_email": None,
                "status": None,
                "used_at": None,
                "message": None,
                "error": f"查询兑换码绑定邮箱失败: {str(e)}"
            }

    async def withdraw_record_by_code(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        根据兑换码撤回当前绑定邮箱对应的最新使用记录。

        前台自助撤销已关闭；该方法仅保留给受控内部流程复用后台使用记录的
        withdraw_record 逻辑，以保持 Team 成员/邀请处理、兑换码恢复、记录删除语义一致。

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典
        """
        normalized_code = (code or "").strip()
        if not normalized_code:
            return {"success": False, "error": "兑换码不能为空"}

        try:
            code_stmt = select(RedemptionCode).where(RedemptionCode.code == normalized_code)
            code_result = await db_session.execute(code_stmt)
            redemption_code = code_result.scalar_one_or_none()

            if not redemption_code:
                return {"success": False, "error": "兑换码不存在"}

            used_by_email = (redemption_code.used_by_email or "").strip()
            if not used_by_email:
                return {"success": False, "error": "该兑换码当前未绑定邮箱，无需撤销"}

            record_stmt = (
                select(RedemptionRecord)
                .where(
                    RedemptionRecord.code == normalized_code,
                    RedemptionRecord.email == used_by_email,
                )
                .order_by(RedemptionRecord.redeemed_at.desc(), RedemptionRecord.id.desc())
            )
            record_result = await db_session.execute(record_stmt)
            record = record_result.scalars().first()

            if not record:
                return {"success": False, "error": "未找到可撤销的使用记录"}

            return await self.withdraw_record(record.id, db_session)

        except Exception as e:
            logger.error(f"按兑换码撤回绑定邮箱失败: {e}")
            return {"success": False, "error": f"撤销失败: {str(e)}"}

    async def get_unused_codes(
        self,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        获取未使用的兑换码

        Args:
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, codes, total, error
        """
        try:
            stmt = select(RedemptionCode).where(
                RedemptionCode.status == "unused"
            ).order_by(RedemptionCode.created_at.desc())

            result = await db_session.execute(stmt)
            codes = result.scalars().all()

            # 构建返回数据
            code_list = []
            for code in codes:
                code_list.append({
                    "id": code.id,
                    "code": code.code,
                    "status": code.status,
                    "created_at": code.created_at.isoformat() if code.created_at else None,
                    "expires_at": code.expires_at.isoformat() if code.expires_at else None,
                    "bound_team_id": code.bound_team_id
                })

            return {
                "success": True,
                "codes": code_list,
                "total": len(code_list),
                "error": None
            }

        except Exception as e:
            logger.error(f"获取未使用兑换码失败: {e}")
            return {
                "success": False,
                "codes": [],
                "total": 0,
                "error": f"获取未使用兑换码失败: {str(e)}"
            }

    async def get_all_records(
        self,
        db_session: AsyncSession,
        email: Optional[str] = None,
        code: Optional[str] = None,
        team_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        获取所有兑换记录 (支持筛选)

        Args:
            db_session: 数据库会话
            email: 邮箱模糊搜索
            code: 兑换码模糊搜索
            team_id: Team ID 筛选

        Returns:
            结果字典,包含 success, records, total, error
        """
        try:
            stmt = select(RedemptionRecord)
            
            # 添加筛选条件
            filters = []
            if email:
                filters.append(RedemptionRecord.email.ilike(f"%{email}%"))
            if code:
                filters.append(RedemptionRecord.code.ilike(f"%{code}%"))
            if team_id:
                filters.append(RedemptionRecord.team_id == team_id)
                
            if filters:
                stmt = stmt.where(and_(*filters))
                
            stmt = stmt.order_by(RedemptionRecord.redeemed_at.desc())
            
            result = await db_session.execute(stmt)
            records = result.scalars().all()

            # 构建返回数据
            record_list = []
            for record in records:
                record_list.append({
                    "id": record.id,
                    "email": record.email,
                    "code": record.code,
                    "team_id": record.team_id,
                    "account_id": record.account_id,
                    "redeemed_at": record.redeemed_at.isoformat() if record.redeemed_at else None
                })

            logger.info(f"获取所有兑换记录成功: 共 {len(record_list)} 条")

            return {
                "success": True,
                "records": record_list,
                "total": len(record_list),
                "error": None
            }

        except Exception as e:
            logger.error(f"获取所有兑换记录失败: {e}")
            return {
                "success": False,
                "records": [],
                "total": 0,
                "error": f"获取所有兑换记录失败: {str(e)}"
            }

    async def delete_code(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        删除兑换码

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 查询兑换码
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": False,
                    "message": None,
                    "error": f"兑换码 {code} 不存在"
                }

            if redemption_code.status != "unused":
                return {
                    "success": False,
                    "message": None,
                    "error": "仅允许删除未使用的兑换码"
                }

            used_code_set = await self._get_usage_record_code_set(db_session, [code])
            if code in used_code_set:
                return {
                    "success": False,
                    "message": None,
                    "error": "该兑换码已有使用记录，不能删除"
                }

            # 删除兑换码
            await db_session.delete(redemption_code)
            await db_session.commit()

            logger.info(f"删除兑换码成功: {code}")

            return {
                "success": True,
                "message": f"兑换码 {code} 已删除",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"删除兑换码失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"删除兑换码失败: {str(e)}"
            }

    async def update_code(
        self,
        code: str,
        db_session: AsyncSession,
        has_warranty: Optional[bool] = None,
        warranty_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """更新兑换码信息"""
        return await self.bulk_update_codes([code], db_session, has_warranty, warranty_days)

    async def withdraw_record(
        self,
        record_id: int,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        撤回使用记录 (删除记录,恢复兑换码,并在 Team 中移除成员/邀请)

        Args:
            record_id: 记录 ID
            db_session: 数据库会话

        Returns:
            结果字典
        """
        try:
            from app.services.team import team_service
            
            # 1. 查询记录
            stmt = select(RedemptionRecord).where(RedemptionRecord.id == record_id).options(
                selectinload(RedemptionRecord.redemption_code)
            )
            result = await db_session.execute(stmt)
            record = result.scalar_one_or_none()

            if not record:
                return {"success": False, "error": f"记录 ID {record_id} 不存在"}

            # 2. 调用 TeamService 移除成员/邀请
            logger.info(f"正在从 Team {record.team_id} 中移除成员 {record.email}")
            team_result = await team_service.remove_invite_or_member(
                record.team_id,
                record.email,
                db_session
            )

            if not team_result["success"]:
                # 即使 Team 移除失败，如果是因为成员已经不在了，我们也继续处理数据库
                if "成员已不存在" not in str(team_result.get("message", "")) and "用户不存在" not in str(team_result.get("error", "")):
                    return {
                        "success": False, 
                        "error": f"从 Team 移除成员失败: {team_result.get('error') or team_result.get('message')}"
                    }

            # 3. 恢复兑换码状态
            code = record.redemption_code
            if code:
                # 如果是质保兑换，且还有其他记录，状态可能不应该直接回 unused
                # 但根据逻辑，目前一个码一个记录（除了质保补发可能产生新记录，但那是两个不同的码吧？）
                # 查了一下模型，RedemptionCode 有 used_by_email 等字段，说明它是单次使用的设计
                code.status = "unused"
                code.used_by_email = None
                code.used_team_id = None
                code.used_at = None
                # 特殊处理质保字段
                if code.has_warranty:
                    code.warranty_expires_at = None

                    normalized_email = (record.email or "").strip().lower()
                    if normalized_email:
                        warranty_entry_result = await db_session.execute(
                            select(WarrantyEmailEntry).where(
                                WarrantyEmailEntry.email == normalized_email
                            )
                        )
                        warranty_entry = warranty_entry_result.scalar_one_or_none()
                        if warranty_entry:
                            await db_session.delete(warranty_entry)

            # 4. 删除使用记录
            await db_session.delete(record)
            await db_session.commit()

            logger.info(f"撤回记录成功: {record_id}, 邮箱: {record.email}, 兑换码: {record.code}")

            return {
                "success": True,
                "message": f"成功撤回记录并恢复兑换码 {record.code}"
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"撤回记录失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": f"撤回失败: {str(e)}"}

    async def bulk_update_codes(
        self,
        codes: List[str],
        db_session: AsyncSession,
        has_warranty: Optional[bool] = None,
        warranty_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        批量更新兑换码信息

        Args:
            codes: 兑换码列表
            db_session: 数据库会话
            has_warranty: 是否为质保兑换码 (可选)
            warranty_days: 质保天数 (可选)

        Returns:
            结果字典
        """
        try:
            if not codes:
                return {"success": True, "message": "没有需要更新的兑换码"}

            stmt = select(RedemptionCode).where(RedemptionCode.code.in_(codes))
            result = await db_session.execute(stmt)
            existing_codes = result.scalars().all()
            existing_code_map = {code.code: code for code in existing_codes}

            missing_codes = [code for code in codes if code not in existing_code_map]
            if missing_codes:
                return {
                    "success": False,
                    "message": None,
                    "error": f"以下兑换码不存在: {', '.join(missing_codes[:5])}"
                }

            used_code_set = await self._get_usage_record_code_set(db_session, codes)
            non_unused_codes = [
                code.code
                for code in existing_codes
                if code.status != "unused" or code.code in used_code_set
            ]
            if non_unused_codes:
                return {
                    "success": False,
                    "message": None,
                    "error": "仅允许修改未使用的兑换码"
                }

            # 构建更新语句
            values = {}
            if has_warranty is not None:
                values[RedemptionCode.has_warranty] = has_warranty
            if warranty_days is not None:
                values[RedemptionCode.warranty_days] = warranty_days

            if not values:
                return {"success": True, "message": "没有提供更新内容"}

            stmt = update(RedemptionCode).where(RedemptionCode.code.in_(codes)).values(values)
            await db_session.execute(stmt)
            await db_session.commit()

            logger.info(f"成功批量更新 {len(codes)} 个兑换码")

            return {
                "success": True,
                "message": f"成功批量更新 {len(codes)} 个兑换码",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"批量更新兑换码失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"批量更新失败: {str(e)}"
            }

    async def bulk_update_unused_warranty_code_quota(
        self,
        codes: List[str],
        db_session: AsyncSession,
        remaining_days: int,
        remaining_claims: int,
    ) -> Dict[str, Any]:
        """批量修改未使用质保兑换码的初始剩余天数和次数"""
        try:
            normalized_codes = list(dict.fromkeys([
                (code or "").strip()
                for code in codes
                if (code or "").strip()
            ]))
            if not normalized_codes:
                return {
                    "success": False,
                    "message": None,
                    "error": "请先选择或筛选要修改的兑换码",
                    "updated_count": 0,
                    "skipped_count": 0,
                }

            try:
                remaining_days_int = int(remaining_days)
                remaining_claims_int = int(remaining_claims)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "message": None,
                    "error": "剩余天数和剩余次数必须是非负整数",
                    "updated_count": 0,
                    "skipped_count": 0,
                }

            if remaining_days_int < 0 or remaining_claims_int < 0:
                return {
                    "success": False,
                    "message": None,
                    "error": "剩余天数和剩余次数必须是非负整数",
                    "updated_count": 0,
                    "skipped_count": 0,
                }

            stmt = select(RedemptionCode).where(RedemptionCode.code.in_(normalized_codes))
            result = await db_session.execute(stmt)
            existing_codes = result.scalars().all()
            existing_code_set = {code.code for code in existing_codes}
            missing_codes = [code for code in normalized_codes if code not in existing_code_set]
            if missing_codes:
                return {
                    "success": False,
                    "message": None,
                    "error": f"以下兑换码不存在: {', '.join(missing_codes[:5])}",
                    "updated_count": 0,
                    "skipped_count": len(existing_codes),
                }

            used_code_set = await self._get_usage_record_code_set(db_session, normalized_codes)
            eligible_codes = [
                code.code
                for code in existing_codes
                if (
                    code.status == "unused"
                    and code.has_warranty
                    and code.code not in used_code_set
                )
            ]
            skipped_count = len(existing_codes) - len(eligible_codes)
            if not eligible_codes:
                return {
                    "success": False,
                    "message": None,
                    "error": "未找到可修改的未使用质保兑换码",
                    "updated_count": 0,
                    "skipped_count": skipped_count,
                }

            update_stmt = (
                update(RedemptionCode)
                .where(RedemptionCode.code.in_(eligible_codes))
                .values({
                    RedemptionCode.warranty_days: remaining_days_int,
                    RedemptionCode.warranty_claims: remaining_claims_int,
                    RedemptionCode.warranty_expires_at: None,
                })
            )
            await db_session.execute(update_stmt)
            await db_session.commit()

            logger.info(
                "成功批量修改 %s 个未使用质保兑换码的剩余天数/次数，跳过 %s 个",
                len(eligible_codes),
                skipped_count,
            )

            return {
                "success": True,
                "message": f"成功修改 {len(eligible_codes)} 个未使用质保兑换码",
                "updated_count": len(eligible_codes),
                "skipped_count": skipped_count,
                "error": None,
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"批量修改未使用质保兑换码剩余次数失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"批量修改失败: {str(e)}",
                "updated_count": 0,
                "skipped_count": 0,
            }

    async def get_stats(
        self,
        db_session: AsyncSession
    ) -> Dict[str, int]:
        """
        获取兑换码统计信息
        
        Returns:
            统计字典, 包含 total, unused, used, expired
        """
        try:
            total_stmt = select(func.count(RedemptionCode.id))
            total_result = await db_session.execute(total_stmt)
            total = total_result.scalar() or 0

            used_stmt = select(func.count(RedemptionCode.id)).where(or_(
                self._usage_record_exists_clause(),
                RedemptionCode.status.in_(["used", "warranty_active"]),
            ))
            used_result = await db_session.execute(used_stmt)
            used_count = used_result.scalar() or 0

            unused_stmt = select(func.count(RedemptionCode.id)).where(and_(
                RedemptionCode.status == "unused",
                ~self._usage_record_exists_clause(),
            ))
            unused_result = await db_session.execute(unused_stmt)
            unused_count = unused_result.scalar() or 0

            warranty_active_stmt = select(func.count(RedemptionCode.id)).where(
                RedemptionCode.status == "warranty_active"
            )
            warranty_active_result = await db_session.execute(warranty_active_stmt)
            warranty_active_count = warranty_active_result.scalar() or 0

            expired_stmt = select(func.count(RedemptionCode.id)).where(and_(
                RedemptionCode.status == "expired",
                ~self._usage_record_exists_clause(),
            ))
            expired_result = await db_session.execute(expired_stmt)
            expired_count = expired_result.scalar() or 0
            
            return {
                "total": total,
                "unused": unused_count,
                "used": used_count,
                "warranty_active": warranty_active_count,
                "expired": expired_count
            }
        except Exception as e:
            logger.error(f"获取兑换码统计信息失败: {e}")
            return {
                "total": 0,
                "unused": 0,
                "used": 0,
                "expired": 0
            }


# 创建全局兑换码服务实例
redemption_service = RedemptionService()
