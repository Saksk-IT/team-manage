"""
质保服务
处理用户质保查询和验证
"""
import logging
import asyncio
import math
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import RedemptionCode, RedemptionRecord, Team, TeamMemberSnapshot, WarrantyEmailEntry
from app.services.settings import settings_service
from app.services.team import TEAM_TYPE_WARRANTY
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)

# 全局频率限制字典: {(type, key): last_time}
# type: 'email' or 'code'
_query_rate_limit = {}


class WarrantyService:
    """质保服务类"""

    AUTO_WARRANTY_ENTRY_DEFAULT_DAYS = 30
    AUTO_WARRANTY_ENTRY_DEFAULT_CLAIMS = 10

    TEAM_STATUS_LABELS = {
        "active": "正常",
        "full": "已满",
        "expired": "已过期",
        "error": "异常",
        "banned": "封禁",
        "no_record": "暂无记录",
    }

    def __init__(self):
        """初始化质保服务"""
        from app.services.team import TeamService
        self.team_service = TeamService()

    def normalize_email(self, email: str) -> str:
        return (email or "").strip().lower()

    def get_team_status_label(self, status: Optional[str]) -> str:
        normalized_status = (status or "").strip().lower()
        return self.TEAM_STATUS_LABELS.get(normalized_status, "未知")

    def _build_warranty_entry_expires_at(self, remaining_days: Optional[int]) -> Optional[datetime]:
        if remaining_days is None:
            return None
        try:
            remaining_days_int = int(remaining_days)
        except (TypeError, ValueError):
            raise ValueError("剩余天数必须是非负整数")

        if remaining_days_int < 0:
            raise ValueError("剩余天数必须是非负整数")

        if remaining_days_int == 0:
            return get_now()

        return get_now() + timedelta(days=remaining_days_int)

    def _get_warranty_entry_remaining_days(self, entry: WarrantyEmailEntry) -> Optional[int]:
        if not entry or not entry.expires_at:
            return None

        remaining_seconds = (entry.expires_at - get_now()).total_seconds()
        if remaining_seconds <= 0:
            return 0

        return max(math.ceil(remaining_seconds / 86400), 0)

    def serialize_warranty_email_entry(self, entry: WarrantyEmailEntry) -> Dict[str, Any]:
        remaining_days = self._get_warranty_entry_remaining_days(entry)
        remaining_claims = max(int(entry.remaining_claims or 0), 0)

        if remaining_claims <= 0 and not entry.expires_at:
            status = "inactive"
            status_label = "未启用"
        elif remaining_claims <= 0:
            status = "claims_exhausted"
            status_label = "次数耗尽"
        elif remaining_days is None:
            status = "inactive"
            status_label = "未启用"
        elif remaining_days <= 0:
            status = "expired"
            status_label = "已过期"
        else:
            status = "active"
            status_label = "有效"

        return {
            "id": entry.id,
            "email": entry.email,
            "remaining_claims": remaining_claims,
            "remaining_days": remaining_days,
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
            "source": entry.source or "auto_redeem",
            "source_label": "质保兑换码自动入列" if (entry.source or "auto_redeem") == "auto_redeem" else "管理员手动维护",
            "last_redeem_code": entry.last_redeem_code,
            "last_warranty_team_id": entry.last_warranty_team_id,
            "status": status,
            "status_label": status_label,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
        }

    async def get_warranty_email_entry(
        self,
        db_session: AsyncSession,
        email: str
    ) -> Optional[WarrantyEmailEntry]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return None

        result = await db_session.execute(
            select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == normalized_email)
        )
        return result.scalar_one_or_none()

    async def list_warranty_email_entries(
        self,
        db_session: AsyncSession,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        stmt = select(WarrantyEmailEntry)
        normalized_search = (search or "").strip()
        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            stmt = stmt.where(
                or_(
                    WarrantyEmailEntry.email.ilike(search_pattern),
                    WarrantyEmailEntry.last_redeem_code.ilike(search_pattern),
                )
            )

        stmt = stmt.order_by(WarrantyEmailEntry.updated_at.desc(), WarrantyEmailEntry.created_at.desc())
        result = await db_session.execute(stmt)
        return [self.serialize_warranty_email_entry(entry) for entry in result.scalars().all()]

    async def save_warranty_email_entry(
        self,
        db_session: AsyncSession,
        email: str,
        remaining_claims: int,
        remaining_days: Optional[int],
        source: str = "manual",
        entry_id: Optional[int] = None
    ) -> WarrantyEmailEntry:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            raise ValueError("邮箱不能为空")

        try:
            remaining_claims_int = int(remaining_claims)
        except (TypeError, ValueError):
            raise ValueError("剩余次数必须是非负整数")

        if remaining_claims_int < 0:
            raise ValueError("剩余次数必须是非负整数")

        expires_at = self._build_warranty_entry_expires_at(remaining_days)

        current_entry = None
        if entry_id is not None:
            result = await db_session.execute(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == entry_id)
            )
            current_entry = result.scalar_one_or_none()
            if not current_entry:
                raise ValueError("质保邮箱记录不存在")

        existing_entry = await self.get_warranty_email_entry(db_session, normalized_email)
        if existing_entry and current_entry and existing_entry.id != current_entry.id:
            raise ValueError("该邮箱已存在其他质保记录")

        target_entry = current_entry or existing_entry
        if target_entry:
            target_entry.email = normalized_email
            target_entry.remaining_claims = remaining_claims_int
            target_entry.expires_at = expires_at
            target_entry.source = source or target_entry.source or "manual"
        else:
            target_entry = WarrantyEmailEntry(
                email=normalized_email,
                remaining_claims=remaining_claims_int,
                expires_at=expires_at,
                source=source or "manual"
            )
            db_session.add(target_entry)

        await db_session.commit()
        await db_session.refresh(target_entry)
        return target_entry

    async def delete_warranty_email_entry(
        self,
        db_session: AsyncSession,
        entry_id: int
    ) -> bool:
        result = await db_session.execute(
            select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            return False

        await db_session.delete(entry)
        await db_session.commit()
        return True

    async def sync_warranty_email_entry_after_redeem(
        self,
        db_session: AsyncSession,
        email: str,
        redeem_code: str,
        has_warranty_code: bool = False
    ) -> Optional[WarrantyEmailEntry]:
        if not has_warranty_code:
            return None

        normalized_email = self.normalize_email(email)
        result = await db_session.execute(
            select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == normalized_email)
        )
        entry = result.scalar_one_or_none()
        default_expires_at = self._build_warranty_entry_expires_at(self.AUTO_WARRANTY_ENTRY_DEFAULT_DAYS)

        if entry:
            entry.last_redeem_code = redeem_code
            if (entry.source or "auto_redeem") == "auto_redeem":
                entry.remaining_claims = self.AUTO_WARRANTY_ENTRY_DEFAULT_CLAIMS
                entry.expires_at = default_expires_at
        else:
            entry = WarrantyEmailEntry(
                email=normalized_email,
                remaining_claims=self.AUTO_WARRANTY_ENTRY_DEFAULT_CLAIMS,
                expires_at=default_expires_at,
                source="auto_redeem",
                last_redeem_code=redeem_code
            )
            db_session.add(entry)

        await db_session.flush()
        return entry

    async def _consume_warranty_claim(
        self,
        db_session: AsyncSession,
        entry: WarrantyEmailEntry
    ) -> None:
        entry.remaining_claims = max(int(entry.remaining_claims or 0) - 1, 0)
        await db_session.commit()
        await db_session.refresh(entry)

    async def _record_warranty_claim_success(
        self,
        db_session: AsyncSession,
        entry: WarrantyEmailEntry,
        email: str,
        team: Team
    ) -> None:
        entry.last_warranty_team_id = team.id

        if entry.last_redeem_code:
            db_session.add(
                RedemptionRecord(
                    email=self.normalize_email(email),
                    code=entry.last_redeem_code,
                    team_id=team.id,
                    account_id=team.account_id,
                    is_warranty_redemption=True,
                    warranty_super_code_type=None
                )
            )

        await self._consume_warranty_claim(db_session, entry)

    async def _get_latest_team_record_for_email(
        self,
        db_session: AsyncSession,
        email: str
    ) -> tuple[Optional[RedemptionRecord], Optional[Team]]:
        normalized_email = self.normalize_email(email)
        stmt = (
            select(RedemptionRecord, Team)
            .join(Team, RedemptionRecord.team_id == Team.id)
            .where(func.lower(RedemptionRecord.email) == normalized_email)
            .order_by(RedemptionRecord.redeemed_at.desc(), RedemptionRecord.id.desc())
        )
        result = await db_session.execute(stmt)
        latest_row = result.first()
        if not latest_row:
            return None, None
        return latest_row[0], latest_row[1]

    async def _get_latest_team_record_for_email_and_team(
        self,
        db_session: AsyncSession,
        email: str,
        team_id: int
    ) -> Optional[RedemptionRecord]:
        normalized_email = self.normalize_email(email)
        stmt = (
            select(RedemptionRecord)
            .where(
                func.lower(RedemptionRecord.email) == normalized_email,
                RedemptionRecord.team_id == team_id
            )
            .order_by(RedemptionRecord.redeemed_at.desc(), RedemptionRecord.id.desc())
        )
        result = await db_session.execute(stmt)
        return result.scalars().first()

    async def _get_latest_team_snapshot_for_email(
        self,
        db_session: AsyncSession,
        email: str
    ) -> tuple[Optional[TeamMemberSnapshot], Optional[Team]]:
        normalized_email = self.normalize_email(email)

        joined_stmt = (
            select(TeamMemberSnapshot, Team)
            .join(Team, TeamMemberSnapshot.team_id == Team.id)
            .where(TeamMemberSnapshot.email == normalized_email)
            .where(TeamMemberSnapshot.member_state == "joined")
            .order_by(TeamMemberSnapshot.updated_at.desc(), TeamMemberSnapshot.id.desc())
        )
        joined_result = await db_session.execute(joined_stmt)
        joined_row = joined_result.first()
        if joined_row:
            return joined_row[0], joined_row[1]

        invited_stmt = (
            select(TeamMemberSnapshot, Team)
            .join(Team, TeamMemberSnapshot.team_id == Team.id)
            .where(TeamMemberSnapshot.email == normalized_email)
            .order_by(TeamMemberSnapshot.updated_at.desc(), TeamMemberSnapshot.id.desc())
        )
        invited_result = await db_session.execute(invited_stmt)
        invited_row = invited_result.first()
        if invited_row:
            return invited_row[0], invited_row[1]

        return None, None

    async def _get_latest_team_snapshot_for_email_and_team(
        self,
        db_session: AsyncSession,
        email: str,
        team_id: int
    ) -> Optional[TeamMemberSnapshot]:
        normalized_email = self.normalize_email(email)

        joined_stmt = (
            select(TeamMemberSnapshot)
            .where(
                TeamMemberSnapshot.team_id == team_id,
                TeamMemberSnapshot.email == normalized_email,
                TeamMemberSnapshot.member_state == "joined"
            )
            .order_by(TeamMemberSnapshot.updated_at.desc(), TeamMemberSnapshot.id.desc())
        )
        joined_result = await db_session.execute(joined_stmt)
        joined_snapshot = joined_result.scalars().first()
        if joined_snapshot:
            return joined_snapshot

        invited_stmt = (
            select(TeamMemberSnapshot)
            .where(
                TeamMemberSnapshot.team_id == team_id,
                TeamMemberSnapshot.email == normalized_email
            )
            .order_by(TeamMemberSnapshot.updated_at.desc(), TeamMemberSnapshot.id.desc())
        )
        invited_result = await db_session.execute(invited_stmt)
        return invited_result.scalars().first()

    def _serialize_warranty_entry_team_info(
        self,
        entry: WarrantyEmailEntry,
        team: Team
    ) -> Dict[str, Any]:
        team_status = (team.status or "").strip().lower()
        latest_joined_at = entry.updated_at or entry.created_at
        return {
            "id": team.id,
            "team_name": team.team_name,
            "email": team.email,
            "account_id": team.account_id,
            "status": team_status or "no_record",
            "status_label": self.get_team_status_label(team_status or "no_record"),
            "redeemed_at": latest_joined_at.isoformat() if latest_joined_at else None,
            "expires_at": team.expires_at.isoformat() if team and team.expires_at else None,
            "code": entry.last_redeem_code,
            "is_warranty_redemption": False,
        }

    async def _load_latest_team_context_from_warranty_entry(
        self,
        db_session: AsyncSession,
        entry: Optional[WarrantyEmailEntry]
    ) -> Optional[Dict[str, Any]]:
        if not entry or not entry.last_warranty_team_id:
            return None

        team = await db_session.get(Team, entry.last_warranty_team_id)
        if not team:
            return None

        latest_record = await self._get_latest_team_record_for_email_and_team(
            db_session,
            entry.email,
            team.id
        )
        if latest_record:
            return {
                "record": latest_record,
                "team": team,
                "team_info": self._serialize_latest_team_info(latest_record, team),
            }

        latest_snapshot = await self._get_latest_team_snapshot_for_email_and_team(
            db_session,
            entry.email,
            team.id
        )
        if latest_snapshot:
            return {
                "snapshot": latest_snapshot,
                "team": team,
                "team_info": self._serialize_snapshot_team_info(latest_snapshot, team),
            }

        return {
            "warranty_entry": entry,
            "team": team,
            "team_info": self._serialize_warranty_entry_team_info(entry, team),
        }

    async def _load_latest_team_context_for_email(
        self,
        db_session: AsyncSession,
        email: str,
        warranty_entry: Optional[WarrantyEmailEntry] = None
    ) -> Optional[Dict[str, Any]]:
        warranty_entry_context = await self._load_latest_team_context_from_warranty_entry(
            db_session,
            warranty_entry
        )
        if warranty_entry_context:
            return warranty_entry_context

        normalized_email = self.normalize_email(email)
        latest_record, latest_team = await self._get_latest_team_record_for_email(
            db_session,
            normalized_email
        )
        if latest_record and latest_team:
            return {
                "record": latest_record,
                "team": latest_team,
                "team_info": self._serialize_latest_team_info(latest_record, latest_team),
            }

        latest_snapshot, latest_snapshot_team = await self._get_latest_team_snapshot_for_email(
            db_session,
            normalized_email
        )
        if latest_snapshot and latest_snapshot_team:
            return {
                "snapshot": latest_snapshot,
                "team": latest_snapshot_team,
                "team_info": self._serialize_snapshot_team_info(latest_snapshot, latest_snapshot_team),
            }

        return None

    async def _refresh_latest_team_context_for_email(
        self,
        db_session: AsyncSession,
        email: str,
        warranty_entry: Optional[WarrantyEmailEntry] = None
    ) -> Optional[Dict[str, Any]]:
        latest_context = await self._load_latest_team_context_for_email(
            db_session,
            email,
            warranty_entry=warranty_entry
        )
        if not latest_context:
            return None

        latest_team = latest_context.get("team")
        if not latest_team:
            return latest_context

        try:
            sync_result = await self.team_service.sync_team_info(latest_team.id, db_session)
            if not sync_result.get("success"):
                logger.warning(
                    "质保状态查询刷新最近 Team 失败，回退到当前缓存状态 email=%s team_id=%s error=%s",
                    self.normalize_email(email),
                    latest_team.id,
                    sync_result.get("error")
                )
                return latest_context
        except Exception as exc:
            logger.warning(
                "质保状态查询刷新最近 Team 异常，回退到当前缓存状态 email=%s team_id=%s error=%s",
                self.normalize_email(email),
                latest_team.id,
                exc
            )
            return latest_context

        refreshed_context = await self._load_latest_team_context_for_email(
            db_session,
            email,
            warranty_entry=warranty_entry
        )
        return refreshed_context or latest_context

    def _serialize_latest_team_info(
        self,
        record: RedemptionRecord,
        team: Team
    ) -> Dict[str, Any]:
        team_status = (team.status or "").strip().lower()
        return {
            "id": team.id,
            "team_name": team.team_name,
            "email": team.email,
            "account_id": team.account_id,
            "status": team_status,
            "status_label": self.get_team_status_label(team_status),
            "redeemed_at": record.redeemed_at.isoformat() if record and record.redeemed_at else None,
            "expires_at": team.expires_at.isoformat() if team and team.expires_at else None,
            "code": record.code if record else None,
            "is_warranty_redemption": bool(record.is_warranty_redemption) if record else False,
        }

    def _serialize_snapshot_team_info(
        self,
        snapshot: TeamMemberSnapshot,
        team: Team
    ) -> Dict[str, Any]:
        team_status = (team.status or "").strip().lower()
        member_state = (snapshot.member_state or "").strip().lower()
        return {
            "id": team.id,
            "team_name": team.team_name,
            "email": team.email,
            "account_id": team.account_id,
            "status": team_status or "no_record",
            "status_label": self.get_team_status_label(team_status or "no_record"),
            "redeemed_at": snapshot.updated_at.isoformat() if snapshot and snapshot.updated_at else None,
            "expires_at": team.expires_at.isoformat() if team and team.expires_at else None,
            "code": None,
            "is_warranty_redemption": False,
            "member_state": member_state,
        }

    async def get_warranty_claim_status(
        self,
        db_session: AsyncSession,
        email: str
    ) -> Dict[str, Any]:
        validation_result = await self.validate_warranty_claim_input(
            db_session=db_session,
            email=email,
            require_latest_team_banned=False
        )
        if not validation_result.get("success"):
            return validation_result

        normalized_email = validation_result["normalized_email"]
        warranty_entry = validation_result["warranty_entry"]
        latest_context = await self._refresh_latest_team_context_for_email(
            db_session,
            normalized_email,
            warranty_entry=warranty_entry
        )
        if not latest_context:
            logger.warning("质保状态查询失败: 未找到最近 Team 记录或成员快照 email=%s", normalized_email)
            return {
                "success": False,
                "error": "未找到该邮箱最近加入的 Team 记录，请先手动刷新 Team 或等待系统自动刷新后再试"
            }

        latest_team_info = latest_context["team_info"]

        can_claim = latest_team_info["status"] == "banned"
        if can_claim:
            message = "该邮箱最近加入的 Team 已封禁，可以继续提交质保。"
        else:
            message = f"该邮箱最近加入的 Team 当前状态为「{latest_team_info['status_label']}」，暂不可提交质保。"

        return {
            "success": True,
            "email": normalized_email,
            "can_claim": can_claim,
            "latest_team": latest_team_info,
            "warranty_info": self.serialize_warranty_email_entry(warranty_entry),
            "message": message
        }

    async def _create_warranty_record(
        self,
        db_session: AsyncSession,
        ordinary_code: str,
        email: str,
        team: Team,
        warranty_super_code_type: str
    ) -> None:
        db_session.add(
            RedemptionRecord(
                email=(email or "").strip().lower(),
                code=ordinary_code,
                team_id=team.id,
                account_id=team.account_id,
                is_warranty_redemption=True,
                warranty_super_code_type=warranty_super_code_type
            )
        )
        await db_session.commit()

    def _build_usage_limit_info(
        self,
        max_uses: int,
        used_uses: int
    ) -> Dict[str, Any]:
        remaining_uses = max(max_uses - used_uses, 0)
        return {
            "type": settings_service.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT,
            "type_label": "次数限制超级兑换码",
            "max_uses": max_uses,
            "used_uses": used_uses,
            "remaining_uses": remaining_uses
        }

    def _build_time_limit_info(
        self,
        first_use_at: datetime,
        limit_days: int
    ) -> Dict[str, Any]:
        expires_at = first_use_at + timedelta(days=limit_days)
        remaining_seconds = max(int((expires_at - get_now()).total_seconds()), 0)
        remaining_days = round(remaining_seconds / 86400, 2)
        return {
            "type": settings_service.WARRANTY_SUPER_CODE_TYPE_TIME_LIMIT,
            "type_label": "时间限制超级兑换码",
            "limit_days": limit_days,
            "first_use_at": first_use_at.isoformat() if first_use_at else None,
            "expires_at": expires_at.isoformat(),
            "remaining_seconds": remaining_seconds,
            "remaining_days": remaining_days
        }

    async def _resolve_matched_email(
        self,
        db_session: AsyncSession,
        ordinary_code: str,
        redemption_code: RedemptionCode
    ) -> Optional[str]:
        matched_email = (redemption_code.used_by_email or "").strip().lower()
        if matched_email:
            return matched_email

        record_stmt = (
            select(RedemptionRecord)
            .where(RedemptionRecord.code == ordinary_code)
            .order_by(RedemptionRecord.redeemed_at.desc())
        )
        record_result = await db_session.execute(record_stmt)
        latest_record = record_result.scalars().first()
        if latest_record and latest_record.email:
            return latest_record.email.strip().lower()
        return None

    async def _get_first_ordinary_use_time(
        self,
        db_session: AsyncSession,
        ordinary_code: str,
        redemption_code: RedemptionCode
    ) -> Optional[datetime]:
        if redemption_code.used_at:
            return redemption_code.used_at

        stmt = (
            select(RedemptionRecord)
            .where(
                RedemptionRecord.code == ordinary_code,
                RedemptionRecord.is_warranty_redemption.is_(False)
            )
            .order_by(RedemptionRecord.redeemed_at.asc())
        )
        result = await db_session.execute(stmt)
        first_record = result.scalars().first()
        return first_record.redeemed_at if first_record else None

    async def _count_usage_limit_successes(
        self,
        db_session: AsyncSession,
        ordinary_code: str,
        email: str
    ) -> int:
        stmt = select(func.count(RedemptionRecord.id)).where(
            RedemptionRecord.code == ordinary_code,
            func.lower(RedemptionRecord.email) == (email or "").strip().lower(),
            RedemptionRecord.is_warranty_redemption.is_(True),
            RedemptionRecord.warranty_super_code_type == settings_service.WARRANTY_SUPER_CODE_TYPE_USAGE_LIMIT
        )
        result = await db_session.execute(stmt)
        return result.scalar() or 0

    async def _get_available_warranty_teams(self, db_session: AsyncSession) -> List[Team]:
        stmt = (
            select(Team)
            .where(
                Team.team_type == TEAM_TYPE_WARRANTY,
                Team.status == "active",
                Team.current_members < Team.max_members
            )
            .order_by(Team.created_at.asc())
        )
        result = await db_session.execute(stmt)
        return result.scalars().all()

    async def _find_existing_full_warranty_team_from_records(
        self,
        db_session: AsyncSession,
        ordinary_code: str,
        email: str
    ) -> Optional[Team]:
        normalized_email = (email or "").strip().lower()
        stmt = (
            select(Team)
            .join(RedemptionRecord, RedemptionRecord.team_id == Team.id)
            .where(
                RedemptionRecord.code == ordinary_code,
                func.lower(RedemptionRecord.email) == normalized_email,
                RedemptionRecord.is_warranty_redemption.is_(True),
                Team.team_type == TEAM_TYPE_WARRANTY,
                Team.status == "full"
            )
            .order_by(RedemptionRecord.redeemed_at.desc(), Team.created_at.asc())
        )
        result = await db_session.execute(stmt)
        return result.scalars().first()

    async def _find_existing_warranty_team_for_email(
        self,
        db_session: AsyncSession,
        email: str
    ) -> Optional[Team]:
        normalized_email = (email or "").strip().lower()
        warranty_teams = await self._get_available_warranty_teams(db_session)

        for team in warranty_teams:
            members_result = await self.team_service.get_team_members(team.id, db_session)
            if not members_result.get("success"):
                logger.warning(
                    "检查质保 Team 现有成员失败，跳过 team_id=%s error=%s",
                    team.id,
                    members_result.get("error")
                )
                continue

            all_members = members_result.get("members", [])
            already_exists = any(
                (member.get("email") or "").strip().lower() == normalized_email
                for member in all_members
            )
            if already_exists:
                return team

        return None

    async def _find_existing_full_warranty_team_for_email_from_records(
        self,
        db_session: AsyncSession,
        email: str
    ) -> Optional[Team]:
        normalized_email = self.normalize_email(email)
        stmt = (
            select(Team)
            .join(RedemptionRecord, RedemptionRecord.team_id == Team.id)
            .where(
                func.lower(RedemptionRecord.email) == normalized_email,
                RedemptionRecord.is_warranty_redemption.is_(True),
                Team.team_type == TEAM_TYPE_WARRANTY,
                Team.status == "full"
            )
            .order_by(RedemptionRecord.redeemed_at.desc(), Team.created_at.asc())
        )
        result = await db_session.execute(stmt)
        return result.scalars().first()

    async def _find_existing_warranty_team_from_entry(
        self,
        db_session: AsyncSession,
        entry: WarrantyEmailEntry
    ) -> Optional[Team]:
        if not entry or not entry.last_warranty_team_id:
            return None

        result = await db_session.execute(
            select(Team).where(
                Team.id == entry.last_warranty_team_id,
                Team.team_type == TEAM_TYPE_WARRANTY
            )
        )
        team = result.scalar_one_or_none()
        if not team or team.status not in {"active", "full"}:
            return None

        members_result = await self.team_service.get_team_members(team.id, db_session)
        if not members_result.get("success"):
            return None

        normalized_email = self.normalize_email(entry.email)
        all_members = members_result.get("members", [])
        already_exists = any(
            self.normalize_email(member.get("email")) == normalized_email
            for member in all_members
        )
        return team if already_exists else None

    async def claim_warranty_invite(
        self,
        db_session: AsyncSession,
        email: str
    ) -> Dict[str, Any]:
        try:
            validation_result = await self.validate_warranty_claim_input(
                db_session=db_session,
                email=email,
                require_latest_team_banned=True
            )
            if not validation_result.get("success"):
                return validation_result

            normalized_email = validation_result["normalized_email"]
            warranty_entry = validation_result["warranty_entry"]

            existing_team = await self._find_existing_warranty_team_from_entry(db_session, warranty_entry)
            if not existing_team:
                existing_team = await self._find_existing_full_warranty_team_for_email_from_records(
                    db_session,
                    normalized_email
                )
            if not existing_team:
                existing_team = await self._find_existing_warranty_team_for_email(db_session, normalized_email)

            if existing_team:
                if warranty_entry.last_warranty_team_id != existing_team.id:
                    warranty_entry.last_warranty_team_id = existing_team.id
                    await db_session.commit()
                    await db_session.refresh(warranty_entry)

                return {
                    "success": True,
                    "message": "质保邀请已存在，请直接查收邮箱中的邀请邮件。",
                    "team_info": {
                        "id": existing_team.id,
                        "team_name": existing_team.team_name,
                        "email": existing_team.email,
                        "expires_at": existing_team.expires_at.isoformat() if existing_team.expires_at else None
                    },
                    "warranty_info": self.serialize_warranty_email_entry(warranty_entry)
                }

            warranty_teams = await self._get_available_warranty_teams(db_session)
            if not warranty_teams:
                logger.warning("质保申请失败: 没有可用的质保 Team")
                return {"success": False, "error": "当前没有可用的质保 Team，请稍后再试"}

            last_error = None
            for team in warranty_teams:
                add_result = await self.team_service.add_team_member(team.id, normalized_email, db_session)
                if add_result.get("success"):
                    await self._record_warranty_claim_success(
                        db_session=db_session,
                        entry=warranty_entry,
                        email=normalized_email,
                        team=team
                    )
                    return {
                        "success": True,
                        "message": add_result.get("message") or "质保邀请发送成功，请查收邮箱。",
                        "team_info": {
                            "id": team.id,
                            "team_name": team.team_name,
                            "email": team.email,
                            "expires_at": team.expires_at.isoformat() if team.expires_at else None
                        },
                        "warranty_info": self.serialize_warranty_email_entry(warranty_entry)
                    }

                last_error = add_result.get("error")
                logger.warning(
                    "质保 Team 邀请失败，尝试下一个 team_id=%s error=%s",
                    team.id,
                    last_error
                )

            return {"success": False, "error": last_error or "当前质保 Team 邀请失败，请稍后再试"}

        except Exception as e:
            logger.error(f"质保邀请申请失败: {e}")
            return {"success": False, "error": f"质保申请失败: {str(e)}"}

    async def validate_warranty_claim_input(
        self,
        db_session: AsyncSession,
        email: str,
        require_latest_team_banned: bool = False
    ) -> Dict[str, Any]:
        """
        校验前台质保申请的基础输入：
        1. 邮箱在质保列表中
        2. 质保次数大于 0
        3. 质保有效期仍然有效
        """
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}

        warranty_entry = await self.get_warranty_email_entry(db_session, normalized_email)
        if not warranty_entry:
            logger.warning("质保申请失败: 邮箱不在质保列表中 email=%s", normalized_email)
            return {"success": False, "error": "该邮箱不在质保邮箱列表中"}

        if int(warranty_entry.remaining_claims or 0) <= 0:
            logger.warning("质保申请失败: 质保次数已用尽 email=%s", normalized_email)
            return {"success": False, "error": "该邮箱暂无可用质保次数"}

        if not warranty_entry.expires_at:
            logger.warning("质保申请失败: 质保资格未启用 email=%s", normalized_email)
            return {"success": False, "error": "该邮箱质保资格未启用"}

        if warranty_entry.expires_at <= get_now():
            logger.warning("质保申请失败: 质保资格已过期 email=%s", normalized_email)
            return {"success": False, "error": "该邮箱质保资格已过期"}

        latest_record = None
        latest_team = None
        latest_team_info = None
        if require_latest_team_banned:
            latest_context = await self._load_latest_team_context_for_email(
                db_session,
                normalized_email,
                warranty_entry=warranty_entry
            )
            if not latest_context:
                logger.warning("质保申请失败: 未找到最近 Team 记录或成员快照 email=%s", normalized_email)
                return {
                    "success": False,
                    "error": "未找到该邮箱最近加入的 Team 记录，请先手动刷新 Team 或等待系统自动刷新后再试"
                }

            latest_record = latest_context.get("record")
            latest_team = latest_context.get("team")
            latest_team_info = latest_context.get("team_info")

            if latest_team_info["status"] != "banned":
                logger.warning(
                    "质保申请失败: 最近 Team 未封禁 email=%s status=%s",
                    normalized_email,
                    latest_team_info["status"]
                )
                return {
                    "success": False,
                    "error": f"该邮箱最近加入的 Team 当前状态为「{latest_team_info['status_label']}」，仅封禁后可提交质保"
                }

        return {
            "success": True,
            "normalized_email": normalized_email,
            "warranty_entry": warranty_entry,
            "latest_record": latest_record,
            "latest_team": latest_team,
            "latest_team_info": latest_team_info,
        }

    async def check_warranty_status(
        self,
        db_session: AsyncSession,
        email: Optional[str] = None,
        code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        检查用户质保状态

        Args:
            db_session: 数据库会话
            email: 用户邮箱
            code: 兑换码

        Returns:
            结果字典,包含 success, has_warranty, warranty_valid, warranty_expires_at, 
            banned_teams, can_reuse, original_code, error
        """
        try:
            if not email and not code:
                return {
                    "success": False,
                    "error": "必须提供邮箱或兑换码"
                }

            # 0. 频率限制 (每个邮箱或每个码 30 秒只能查一次)
            now = datetime.now()
            limit_key = ("email", email) if email else ("code", code)
            last_time = _query_rate_limit.get(limit_key)
            if last_time and (now - last_time).total_seconds() < 30:
                wait_time = int(30 - (now - last_time).total_seconds())
                return {
                    "success": False,
                    "error": f"查询太频繁,请 {wait_time} 秒后再试"
                }
            _query_rate_limit[limit_key] = now

            # 1. 查找兑换记录和相关联的 Team, Code
            records_data = []

            if code:
                # 通过兑换码查找所有关联记录
                stmt = (
                    select(RedemptionRecord, RedemptionCode, Team)
                    .options(selectinload(RedemptionRecord.redemption_code), selectinload(RedemptionRecord.team))
                    .join(RedemptionCode, RedemptionRecord.code == RedemptionCode.code)
                    .join(Team, RedemptionRecord.team_id == Team.id)
                    .where(RedemptionCode.code == code)
                    .order_by(RedemptionRecord.redeemed_at.desc())
                )
                result = await db_session.execute(stmt)
                first_record = result.first()
                if first_record:
                    records_data = [first_record]
                else:
                    records_data = []

                # 如果没有记录，可能是码还没被使用或不存在
                if not records_data:
                    stmt = select(RedemptionCode).where(RedemptionCode.code == code)
                    result = await db_session.execute(stmt)
                    redemption_code_obj = result.scalar_one_or_none()
                    
                    if not redemption_code_obj:
                        return {
                            "success": True,
                            "has_warranty": False,
                            "warranty_valid": False,
                            "warranty_expires_at": None,
                            "banned_teams": [],
                            "can_reuse": False,
                            "original_code": None,
                            "records": [],
                            "message": "兑换码不存在"
                        }
                    
                    # 只有码没有记录的情况
                    return {
                        "success": True,
                        "has_warranty": redemption_code_obj.has_warranty,
                        "warranty_valid": True if not redemption_code_obj.warranty_expires_at or redemption_code_obj.warranty_expires_at > get_now() else False,
                        "warranty_expires_at": redemption_code_obj.warranty_expires_at.isoformat() if redemption_code_obj.warranty_expires_at else None,
                        "banned_teams": [],
                        "can_reuse": False,
                        "original_code": redemption_code_obj.code,
                        "records": [{
                            "code": redemption_code_obj.code,
                            "has_warranty": redemption_code_obj.has_warranty,
                            "warranty_valid": True if not redemption_code_obj.warranty_expires_at or redemption_code_obj.warranty_expires_at > get_now() else False,
                            "status": redemption_code_obj.status,
                            "used_at": None,
                            "team_id": None,
                            "team_name": None,
                            "team_status": None,
                            "team_expires_at": None,
                            "warranty_expires_at": redemption_code_obj.warranty_expires_at.isoformat() if redemption_code_obj.warranty_expires_at else None
                        }],
                        "message": "兑换码尚未被使用"
                    }

            elif email:
                # 通过邮箱查找所有兑换记录
                stmt = (
                    select(RedemptionRecord, RedemptionCode, Team)
                    .options(selectinload(RedemptionRecord.redemption_code), selectinload(RedemptionRecord.team))
                    .join(RedemptionCode, RedemptionRecord.code == RedemptionCode.code)
                    .join(Team, RedemptionRecord.team_id == Team.id)
                    .where(RedemptionRecord.email == email)
                    .order_by(RedemptionRecord.redeemed_at.desc())
                )
                result = await db_session.execute(stmt)
                all_records = result.all()

                # 只保留每个兑换码的最近一条记录
                seen_codes = set()
                records_data = []
                for row in all_records:
                    # row format: (RedemptionRecord, RedemptionCode, Team)
                    record_obj = row[0]
                    if record_obj.code not in seen_codes:
                        seen_codes.add(record_obj.code)
                        records_data.append(row)

            if not records_data:
                return {
                    "success": True,
                    "has_warranty": False,
                    "warranty_valid": False,
                    "warranty_expires_at": None,
                    "banned_teams": [],
                    "can_reuse": False,
                    "original_code": None,
                    "records": [],
                    "message": "未找到兑换记录"
                }

            # 2. 处理记录并进行必要的实时同步
            final_records = []
            banned_teams_info = []
            has_any_warranty = False
            primary_warranty_valid = False
            primary_expiry = None
            primary_code = None
            can_reuse = False

            for record, code_obj, team in records_data:
                # 1.1 实时一致性校验 (自愈逻辑)
                # 如果数据库有记录，但 API 列表里没你，说明是虚假成功，直接后台修复
                if team.status != "banned" and team.status != "expired":
                    logger.info(f"质保查询: 正在实时测试 Team {team.id} ({team.team_name}) 的状态")
                    sync_res = await self.team_service.sync_team_info(team.id, db_session)
                    member_emails = [m.lower() for m in sync_res.get("member_emails", [])]
                    
                    if record.email.lower() not in member_emails:
                        logger.warning(f"自愈逻辑(查询触发): 发现孤儿记录 (Email: {record.email}, Team: {team.id}), API 查无此人。正在执行自动清理。")
                        await db_session.delete(record)
                        await db_session.commit()
                        # 跳过这条无效记录，提示用户重新兑换
                        continue 

                # 动态计算/提取质保信息
                expiry_date = code_obj.warranty_expires_at
                
                # 如果是质保码且已使用，但到期时间为空，尝试动态计算
                if code_obj.has_warranty and not expiry_date:
                    start_time = code_obj.used_at or record.redeemed_at # 优先取首次使用时间
                    if start_time:
                        days = code_obj.warranty_days or 30
                        expiry_date = start_time + timedelta(days=days)

                is_valid = True
                if expiry_date and expiry_date < get_now():
                    is_valid = False
                elif not expiry_date and code_obj.has_warranty and code_obj.status == "unused":
                    # 未使用的质保码，暂时标记为有效
                    is_valid = True
                elif not expiry_date:
                    # 既没日期也没记录，通常是非质保码
                    is_valid = False

                if code_obj.has_warranty:
                    has_any_warranty = True
                    # 以最近的一个质保码作为主要质保状态参考
                    if primary_code is None:
                        primary_warranty_valid = is_valid
                        primary_expiry = expiry_date
                        primary_code = code_obj.code

                # 记录封号 Team
                if team.status == "banned":
                    banned_teams_info.append({
                        "team_id": team.id,
                        "team_name": team.team_name,
                        "email": team.email,
                        "banned_at": team.last_sync.isoformat() if team.last_sync else None
                    })

                final_records.append({
                    "code": code_obj.code,
                    "has_warranty": code_obj.has_warranty,
                    "warranty_valid": is_valid,
                    "warranty_expires_at": expiry_date.isoformat() if expiry_date else None,
                    "status": code_obj.status,
                    "used_at": record.redeemed_at.isoformat() if record.redeemed_at else None,
                    "team_id": team.id,
                    "team_name": team.team_name,
                    "team_status": team.status,
                    "team_expires_at": team.expires_at.isoformat() if team.expires_at else None,
                    "email": record.email,
                    "device_code_auth_enabled": team.device_code_auth_enabled
                })

            # 3. 判断是否可以重复使用 (只要有有效的质保码且有被封的 Team)
            if has_any_warranty and primary_warranty_valid and len(banned_teams_info) > 0:
                # 进一步验证 (使用现有的 validate_warranty_reuse 逻辑)
                # 这里为了简单直接复用逻辑判断
                can_reuse = True

            # 4. 最终状态判定
            message = "查询成功"
            if has_any_warranty and not final_records and records_data:
                # 这种情况说明刚才所有记录都被自愈逻辑删除了（全是虚假成功）
                message = "系统发现您的兑换记录存在同步异常，已为您自动修复！您的兑换码已恢复，请返回兑换页面重新提交一次即可。"
                can_reuse = True

            return {
                "success": True,
                "has_warranty": has_any_warranty,
                "warranty_valid": primary_warranty_valid,
                "warranty_expires_at": primary_expiry.isoformat() if primary_expiry else None,
                "banned_teams": banned_teams_info,
                "can_reuse": can_reuse,
                "original_code": primary_code,
                "records": final_records,
                "message": message
            }

        except Exception as e:
            logger.error(f"检查质保状态失败: {e}")
            return {
                "success": False,
                "error": f"检查质保状态失败: {str(e)}"
            }

    async def validate_warranty_reuse(
        self,
        db_session: AsyncSession,
        code: str,
        email: str
    ) -> Dict[str, Any]:
        """
        验证质保码是否可重复使用

        Args:
            db_session: 数据库会话
            code: 兑换码
            email: 用户邮箱

        Returns:
            结果字典,包含 success, can_reuse, reason, error
        """
        try:
            # 1. 查询兑换码
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": True,
                    "can_reuse": False,
                    "reason": "兑换码不存在",
                    "error": None
                }

            # 2. 检查是否为质保码
            if not redemption_code.has_warranty:
                return {
                    "success": True,
                    "can_reuse": False,
                    "reason": "该兑换码不是质保兑换码",
                    "error": None
                }

            # 3. 检查质保期是否有效
            if redemption_code.warranty_expires_at:
                if redemption_code.warranty_expires_at < get_now():
                    return {
                        "success": True,
                        "can_reuse": False,
                        "reason": "质保已过期",
                        "error": None
                    }

            # 4. 检查该兑换码当前是否已有正在使用的活跃 Team (全局检查，不限邮箱)
            # 逻辑：如果该码名下有任何一个 Team 还是 active/full 状态且未过期，则不允许新的激活
            stmt = select(RedemptionRecord).where(RedemptionRecord.code == code)
            result = await db_session.execute(stmt)
            all_records_for_code = result.scalars().all()
            
            for record in all_records_for_code:
                stmt = select(Team).where(Team.id == record.team_id)
                result = await db_session.execute(stmt)
                team = result.scalar_one_or_none()
                
                if team:
                    is_expired = team.expires_at and team.expires_at < get_now()
                    if team.status in ["active", "full"] and not is_expired:
                        # --- 自愈逻辑：验证是否真的在 Team 中 ---
                        # 针对“虚假成功”导致的拉人记录残留进行清理
                        logger.info(f"验证质保重复使用: 发现活跃 record，正在同步 Team {team.id} 以校验成员是否存在")
                        sync_res = await self.team_service.sync_team_info(team.id, db_session)
                        member_emails = [m.lower() for m in sync_res.get("member_emails", [])]
                        
                        if record.email.lower() not in member_emails:
                            logger.warning(f"自愈逻辑: 发现孤儿记录 (Email: {record.email}, Team: {team.id}), 但同步结果中不包含该成员。正在清理记录。")
                            # 删除该孤儿记录
                            await db_session.delete(record)
                            if not db_session.in_transaction():
                                await db_session.commit()
                            else:
                                await db_session.flush()
                            continue # 继续检查下一个记录或结束循环

                        # 如果是同一个邮箱且确实在 Team 中，提示已在有效 Team 中
                        if record.email == email:
                            return {
                                "success": True,
                                "can_reuse": False,
                                "reason": f"您已在有效 Team 中 ({team.team_name or team.id})，不可重复兑换",
                                "error": None
                            }
                        else:
                            # 如果是不同邮箱，提示已被占用
                            return {
                                "success": True,
                                "can_reuse": False,
                                "reason": "该兑换码当前已被其他账号绑定且正在使用中。如需更换，请确保原账号已下车或原 Team 已失效。",
                                "error": None
                            }

            # 刷新记录列表 (可能在上面自愈逻辑中删除了孤儿记录)
            stmt = select(RedemptionRecord).where(RedemptionRecord.code == code)
            result = await db_session.execute(stmt)
            all_records_for_code = result.scalars().all()

            # 5. 查找当前用户使用该兑换码的记录 (用于后续逻辑判断)
            records = [r for r in all_records_for_code if r.email == email]
            
            if not records:
                # 之前没有该邮箱的记录，但上面已经检查过没有其他活跃 Team 了，所以允许“新开”或“接手”
                return {
                    "success": True,
                    "can_reuse": True,
                    "reason": "可更名使用 (或首次使用)",
                    "error": None
                }

            # 5. 检查用户当前是否已在有效的 Team 中
            # 逻辑：如果最近一次加入的 Team 仍然有效（active/full 且未过期），则不允许重复使用
            for record in records:
                stmt = select(Team).where(Team.id == record.team_id)
                result = await db_session.execute(stmt)
                team = result.scalar_one_or_none()
                
                if team:
                    # 如果有任何一个关联 Team 还是 active/full 状态，且未过期
                    is_expired = team.expires_at and team.expires_at < get_now()
                    if team.status in ["active", "full"] and not is_expired:
                        return {
                            "success": True,
                            "can_reuse": False,
                            "reason": f"您已在有效 Team 中 ({team.team_name or team.id})，不可重复兑换",
                            "error": None
                        }

            # 6. 检查是否有过被封的记录
            has_banned_team = False
            for record in records:
                stmt = select(Team).where(Team.id == record.team_id)
                result = await db_session.execute(stmt)
                team = result.scalar_one_or_none()
                if team and team.status == "banned":
                    has_banned_team = True
                    break
            if has_banned_team:
                return {
                    "success": True,
                    "can_reuse": True,
                    "reason": "之前加入的 Team 已封号，可使用质保重复兑换",
                    "error": None
                }
            else:
                return {
                    "success": True,
                    "can_reuse": False,
                    "reason": "未找到被封号记录，且质保不支持正常过期或异常提示的重复兑换",
                    "error": None
                }

        except Exception as e:
            logger.error(f"验证质保码重复使用失败: {e}")
            return {
                "success": False,
                "can_reuse": False,
                "reason": None,
                "error": f"验证失败: {str(e)}"
            }


# 创建全局质保服务实例
warranty_service = WarrantyService()
