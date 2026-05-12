"""
质保服务
处理用户质保查询和验证
"""
import logging
import asyncio
import math
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    RedemptionCode,
    RedemptionRecord,
    Team,
    TeamMemberSnapshot,
    WarrantyClaimRecord,
    WarrantyEmailEntry,
    WarrantyEmailTemplateLock,
)
from app.services.settings import settings_service
from app.services.sub2api_warranty_client import sub2api_warranty_redeem_client
from app.services.team import IMPORT_STATUS_CLASSIFIED, TEAM_TYPE_STANDARD
from app.services.team_refresh_record import SOURCE_USER_WARRANTY
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

    CLAIM_STATUS_LABELS = {
        "success": "质保成功",
        "failed": "质保失败",
    }

    WARRANTY_EMAIL_STATUS_LABELS = {
        "active": "有效",
        "claims_exhausted": "次数耗尽",
        "expired": "已过期",
        "inactive": "未启用",
    }

    WARRANTY_EMAIL_SOURCE_LABELS = {
        "auto_redeem": "质保兑换码自动入列",
        "manual": "管理员手动维护",
    }
    USABLE_LINKED_TEAM_STATUSES = {"active", "full"}
    TEAM_AVAILABLE_NO_WARRANTY_MESSAGE = "您所在的Team可以正常使用，无需提交质保"
    WARRANTY_EMAIL_MISSING_REDEEM_CODE_MESSAGE = "请加入 QQ 群，联系群主处理。"
    WARRANTY_EMAIL_WRONG_REDEEM_CODE_MESSAGE = "您的质保兑换码错误"

    def __init__(self):
        """初始化质保服务"""
        from app.services.team import TeamService
        self.team_service = TeamService()

    def normalize_email(self, email: str) -> str:
        return (email or "").strip().lower()

    def _should_try_next_warranty_team(self, add_result: Dict[str, Any]) -> bool:
        return bool(add_result.get("allow_try_next_team"))

    def get_team_status_label(self, status: Optional[str]) -> str:
        normalized_status = (status or "").strip().lower()
        return self.TEAM_STATUS_LABELS.get(normalized_status, "未知")

    def _build_warranty_entry_expires_at(
        self,
        remaining_days: Optional[int],
        remaining_seconds: Optional[int] = None,
    ) -> Optional[datetime]:
        if remaining_seconds is not None:
            try:
                remaining_seconds_int = int(remaining_seconds)
            except (TypeError, ValueError):
                raise ValueError("剩余时间必须是非负整数秒")

            if remaining_seconds_int < 0:
                raise ValueError("剩余时间必须是非负整数秒")

            if remaining_seconds_int == 0:
                return get_now()

            return get_now() + timedelta(seconds=remaining_seconds_int)

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

    def _get_warranty_entry_remaining_seconds(self, entry: WarrantyEmailEntry) -> Optional[int]:
        if not entry or not entry.expires_at:
            return None

        return max(int((entry.expires_at - get_now()).total_seconds()), 0)

    def _get_warranty_entry_remaining_days(self, entry: WarrantyEmailEntry) -> Optional[int]:
        remaining_seconds = self._get_warranty_entry_remaining_seconds(entry)
        if remaining_seconds is None:
            return None
        if remaining_seconds <= 0:
            return 0

        return max(math.ceil(remaining_seconds / 86400), 0)

    def _serialize_linked_team_summary(self, team: Optional[Team]) -> Optional[Dict[str, Any]]:
        if not team:
            return None

        team_status = (team.status or "").strip().lower() or "no_record"
        return {
            "id": team.id,
            "team_name": team.team_name,
            "email": team.email,
            "account_id": team.account_id,
            "status": team_status,
            "status_label": self.get_team_status_label(team_status),
            "expires_at": team.expires_at.isoformat() if team.expires_at else None,
        }

    async def _get_usable_linked_team_for_warranty_entries(
        self,
        db_session: AsyncSession,
        entries: List[WarrantyEmailEntry],
    ) -> Optional[Dict[str, Any]]:
        team_ids = {
            int(entry.last_warranty_team_id)
            for entry in entries
            if entry.last_warranty_team_id
        }
        if not team_ids:
            return None

        team_result = await db_session.execute(
            select(Team).where(Team.id.in_(team_ids))
        )
        teams_by_id = {team.id: team for team in team_result.scalars().all()}

        for entry in entries:
            team = teams_by_id.get(int(entry.last_warranty_team_id or 0))
            team_status = (getattr(team, "status", "") or "").strip().lower()
            if team_status in self.USABLE_LINKED_TEAM_STATUSES:
                return self._serialize_linked_team_summary(team)

        return None

    def _serialize_generated_redeem_code_summary(
        self,
        generated_code: Optional[WarrantyEmailTemplateLock],
    ) -> Optional[Dict[str, Any]]:
        if not generated_code or not generated_code.generated_redeem_code:
            return None

        return {
            "code": generated_code.generated_redeem_code,
            "remaining_days": generated_code.generated_redeem_code_remaining_days,
            "generated_at": (
                generated_code.generated_redeem_code_generated_at.isoformat()
                if generated_code.generated_redeem_code_generated_at
                else None
            ),
            "lock_id": generated_code.id,
        }

    async def _get_latest_generated_redeem_codes_by_entry(
        self,
        db_session: AsyncSession,
        entry_models: List[WarrantyEmailEntry],
    ) -> Dict[int, WarrantyEmailTemplateLock]:
        entry_ids = [int(entry.id) for entry in entry_models if entry.id]
        emails = {
            self.normalize_email(entry.email)
            for entry in entry_models
            if self.normalize_email(entry.email)
        }
        if not entry_ids and not emails:
            return {}

        result = await db_session.execute(
            select(WarrantyEmailTemplateLock)
            .where(
                or_(
                    WarrantyEmailTemplateLock.generated_redeem_code_entry_id.in_(entry_ids),
                    WarrantyEmailTemplateLock.email.in_(emails),
                ),
                WarrantyEmailTemplateLock.generated_redeem_code.isnot(None),
            )
            .order_by(
                WarrantyEmailTemplateLock.generated_redeem_code_entry_id.asc(),
                WarrantyEmailTemplateLock.generated_redeem_code_generated_at.desc(),
                WarrantyEmailTemplateLock.id.desc(),
            )
        )

        entry_ids_by_email: Dict[str, List[int]] = {}
        for entry in entry_models:
            normalized_email = self.normalize_email(entry.email)
            if normalized_email and entry.id:
                entry_ids_by_email.setdefault(normalized_email, []).append(int(entry.id))

        generated_by_entry: Dict[int, WarrantyEmailTemplateLock] = {}
        fallback_locks: List[WarrantyEmailTemplateLock] = []
        for lock in result.scalars().all():
            entry_id = int(lock.generated_redeem_code_entry_id or 0)
            if entry_id and entry_id not in generated_by_entry:
                generated_by_entry[entry_id] = lock
            fallback_locks.append(lock)

        for lock in fallback_locks:
            for fallback_entry_id in entry_ids_by_email.get(self.normalize_email(lock.email), []):
                if fallback_entry_id not in generated_by_entry:
                    generated_by_entry[fallback_entry_id] = lock

        return generated_by_entry

    def serialize_warranty_email_entry(
        self,
        entry: WarrantyEmailEntry,
        linked_team: Optional[Team] = None,
        generated_code: Optional[WarrantyEmailTemplateLock] = None,
    ) -> Dict[str, Any]:
        remaining_seconds = self._get_warranty_entry_remaining_seconds(entry)
        remaining_days = (
            max(math.ceil(remaining_seconds / 86400), 0)
            if remaining_seconds is not None
            else None
        )
        remaining_claims = max(int(entry.remaining_claims or 0), 0)

        if remaining_claims <= 0 and not entry.expires_at:
            status = "inactive"
        elif remaining_claims <= 0:
            status = "claims_exhausted"
        elif remaining_days is None:
            status = "inactive"
        elif remaining_days <= 0:
            status = "expired"
        else:
            status = "active"

        source = entry.source or "auto_redeem"
        linked_team_info = self._serialize_linked_team_summary(linked_team)
        generated_code_info = self._serialize_generated_redeem_code_summary(generated_code)

        return {
            "id": entry.id,
            "email": entry.email,
            "remaining_claims": remaining_claims,
            "remaining_days": remaining_days,
            "remaining_seconds": remaining_seconds,
            "remaining_time": self._format_remaining_seconds(remaining_seconds),
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
            "source": source,
            "source_label": self.WARRANTY_EMAIL_SOURCE_LABELS.get(source, "未知来源"),
            "last_redeem_code": entry.last_redeem_code,
            "transfer_redeem_code": generated_code_info.get("code") if generated_code_info else None,
            "transfer_redeem_code_remaining_days": generated_code_info.get("remaining_days") if generated_code_info else None,
            "transfer_redeem_code_generated_at": generated_code_info.get("generated_at") if generated_code_info else None,
            "transfer_redeem_code_lock_id": generated_code_info.get("lock_id") if generated_code_info else None,
            "last_warranty_team_id": entry.last_warranty_team_id,
            "last_warranty_team": linked_team_info,
            "last_warranty_team_name": linked_team_info.get("team_name") if linked_team_info else None,
            "last_warranty_team_email": linked_team_info.get("email") if linked_team_info else None,
            "last_warranty_team_account_id": linked_team_info.get("account_id") if linked_team_info else None,
            "last_warranty_team_status": linked_team_info.get("status") if linked_team_info else None,
            "last_warranty_team_status_label": linked_team_info.get("status_label") if linked_team_info else None,
            "status": status,
            "status_label": self.WARRANTY_EMAIL_STATUS_LABELS.get(status, "未知"),
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None
        }

    def _serialize_warranty_claim_team_snapshot(
        self,
        team_info: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not team_info:
            return {
                "team_id": None,
                "team_name": None,
                "team_email": None,
                "team_account_id": None,
                "team_status": None,
                "team_recorded_at": None,
            }

        return {
            "team_id": team_info.get("id"),
            "team_name": team_info.get("team_name"),
            "team_email": team_info.get("email"),
            "team_account_id": team_info.get("account_id"),
            "team_status": team_info.get("status"),
            "team_recorded_at": team_info.get("redeemed_at"),
        }

    def serialize_warranty_claim_record(self, record: WarrantyClaimRecord) -> Dict[str, Any]:
        claim_status = (record.claim_status or "").strip().lower()
        return {
            "id": record.id,
            "email": record.email,
            "before_team_id": record.before_team_id,
            "before_team_name": record.before_team_name,
            "before_team_email": record.before_team_email,
            "before_team_account_id": record.before_team_account_id,
            "before_team_status": record.before_team_status,
            "before_team_status_label": self.get_team_status_label(record.before_team_status),
            "before_team_recorded_at": record.before_team_recorded_at.isoformat() if record.before_team_recorded_at else None,
            "claim_status": claim_status,
            "claim_status_label": self.CLAIM_STATUS_LABELS.get(claim_status, "未知"),
            "failure_reason": record.failure_reason,
            "after_team_id": record.after_team_id,
            "after_team_name": record.after_team_name,
            "after_team_email": record.after_team_email,
            "after_team_account_id": record.after_team_account_id,
            "after_team_recorded_at": record.after_team_recorded_at.isoformat() if record.after_team_recorded_at else None,
            "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        }

    def _apply_before_team_info_to_claim_record(
        self,
        record_data: Dict[str, Any],
        before_team_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        before_snapshot = self._serialize_warranty_claim_team_snapshot(before_team_info)
        return {
            **record_data,
            "before_team_id": before_snapshot["team_id"],
            "before_team_name": before_snapshot["team_name"],
            "before_team_email": before_snapshot["team_email"],
            "before_team_account_id": before_snapshot["team_account_id"],
            "before_team_status": before_snapshot["team_status"],
            "before_team_status_label": self.get_team_status_label(before_snapshot["team_status"]),
            "before_team_recorded_at": before_snapshot["team_recorded_at"],
        }

    async def _find_legacy_before_team_info_for_claim_record(
        self,
        db_session: AsyncSession,
        record: WarrantyClaimRecord,
    ) -> Optional[Dict[str, Any]]:
        claim_status = (record.claim_status or "").strip().lower()
        if claim_status != "success" or not record.after_team_id:
            return None
        if record.before_team_id not in {None, record.after_team_id}:
            return None

        normalized_email = self.normalize_email(record.email)
        if not normalized_email:
            return None

        cutoff_at = record.submitted_at or record.completed_at or get_now()
        record_stmt = (
            select(RedemptionRecord, Team)
            .join(Team, RedemptionRecord.team_id == Team.id)
            .where(
                func.lower(RedemptionRecord.email) == normalized_email,
                RedemptionRecord.team_id != record.after_team_id,
                RedemptionRecord.redeemed_at <= cutoff_at,
            )
            .order_by(RedemptionRecord.redeemed_at.desc(), RedemptionRecord.id.desc())
        )
        record_result = await db_session.execute(record_stmt)
        record_row = record_result.first()
        if record_row:
            return self._serialize_latest_team_info(record_row[0], record_row[1])

        snapshot_stmt = (
            select(TeamMemberSnapshot, Team)
            .join(Team, TeamMemberSnapshot.team_id == Team.id)
            .where(
                TeamMemberSnapshot.email == normalized_email,
                TeamMemberSnapshot.team_id != record.after_team_id,
                TeamMemberSnapshot.updated_at <= cutoff_at,
            )
            .order_by(TeamMemberSnapshot.updated_at.desc(), TeamMemberSnapshot.id.desc())
        )
        snapshot_result = await db_session.execute(snapshot_stmt)
        snapshot_row = snapshot_result.first()
        if snapshot_row:
            return self._serialize_snapshot_team_info(snapshot_row[0], snapshot_row[1])

        return None

    async def _serialize_warranty_claim_record_for_list(
        self,
        db_session: AsyncSession,
        record: WarrantyClaimRecord,
    ) -> Dict[str, Any]:
        record_data = self.serialize_warranty_claim_record(record)
        before_team_info = await self._find_legacy_before_team_info_for_claim_record(
            db_session,
            record,
        )
        if not before_team_info:
            return record_data
        return self._apply_before_team_info_to_claim_record(record_data, before_team_info)

    async def _record_warranty_claim_result(
        self,
        db_session: AsyncSession,
        email: str,
        submitted_at: datetime,
        claim_status: str,
        before_team_info: Optional[Dict[str, Any]] = None,
        failure_reason: Optional[str] = None,
        after_team: Optional[Team] = None,
        after_team_recorded_at: Optional[datetime] = None,
    ) -> None:
        try:
            normalized_email = self.normalize_email(email)
            before_snapshot = self._serialize_warranty_claim_team_snapshot(before_team_info)
            completed_at = get_now()
            effective_after_recorded_at = after_team_recorded_at or completed_at

            db_session.add(
                WarrantyClaimRecord(
                    email=normalized_email,
                    before_team_id=before_snapshot["team_id"],
                    before_team_name=before_snapshot["team_name"],
                    before_team_email=before_snapshot["team_email"],
                    before_team_account_id=before_snapshot["team_account_id"],
                    before_team_status=before_snapshot["team_status"],
                    before_team_recorded_at=(
                        datetime.fromisoformat(before_snapshot["team_recorded_at"])
                        if before_snapshot["team_recorded_at"]
                        else None
                    ),
                    claim_status=claim_status,
                    failure_reason=failure_reason,
                    after_team_id=after_team.id if after_team else None,
                    after_team_name=after_team.team_name if after_team else None,
                    after_team_email=after_team.email if after_team else None,
                    after_team_account_id=after_team.account_id if after_team else None,
                    after_team_recorded_at=effective_after_recorded_at if after_team else None,
                    submitted_at=submitted_at,
                    completed_at=completed_at,
                )
            )
            await db_session.commit()
        except Exception as exc:
            await db_session.rollback()
            logger.error(
                "写入质保提交记录失败 email=%s status=%s error=%s",
                self.normalize_email(email),
                claim_status,
                exc
            )

    async def list_warranty_claim_records(
        self,
        db_session: AsyncSession,
        search: Optional[str] = None,
        claim_status: Optional[str] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> Dict[str, Any]:
        normalized_status = (claim_status or "").strip().lower()
        normalized_search = (search or "").strip()

        stmt = select(WarrantyClaimRecord)
        count_stmt = select(func.count(WarrantyClaimRecord.id))

        filters = []
        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            filters.append(
                or_(
                    WarrantyClaimRecord.email.ilike(search_pattern),
                    WarrantyClaimRecord.before_team_name.ilike(search_pattern),
                    WarrantyClaimRecord.before_team_email.ilike(search_pattern),
                    WarrantyClaimRecord.before_team_account_id.ilike(search_pattern),
                    WarrantyClaimRecord.after_team_name.ilike(search_pattern),
                    WarrantyClaimRecord.after_team_email.ilike(search_pattern),
                    WarrantyClaimRecord.after_team_account_id.ilike(search_pattern),
                    WarrantyClaimRecord.failure_reason.ilike(search_pattern),
                )
            )

        if normalized_status in self.CLAIM_STATUS_LABELS:
            filters.append(WarrantyClaimRecord.claim_status == normalized_status)

        if filters:
            stmt = stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))

        safe_page = max(int(page or 1), 1)
        safe_per_page = max(int(per_page or 100), 1)
        offset = (safe_page - 1) * safe_per_page

        stmt = (
            stmt.order_by(WarrantyClaimRecord.submitted_at.desc(), WarrantyClaimRecord.id.desc())
            .offset(offset)
            .limit(safe_per_page)
        )

        total_result = await db_session.execute(count_stmt)
        total = total_result.scalar() or 0

        records_result = await db_session.execute(stmt)
        records = [
            await self._serialize_warranty_claim_record_for_list(db_session, record)
            for record in records_result.scalars().all()
        ]

        total_pages = max(math.ceil(total / safe_per_page), 1) if total else 1
        return {
            "records": records,
            "pagination": {
                "current_page": safe_page,
                "per_page": safe_per_page,
                "total": total,
                "total_pages": total_pages,
            }
        }

    async def get_warranty_email_entry(
        self,
        db_session: AsyncSession,
        email: str
    ) -> Optional[WarrantyEmailEntry]:
        entries = await self.get_warranty_email_entries_for_email(db_session, email)
        if not entries:
            return None
        return entries[0]

    async def get_warranty_email_entry_by_id(
        self,
        db_session: AsyncSession,
        entry_id: Optional[int],
        email: Optional[str] = None,
    ) -> Optional[WarrantyEmailEntry]:
        try:
            safe_entry_id = int(entry_id or 0)
        except (TypeError, ValueError):
            return None
        if safe_entry_id <= 0:
            return None

        stmt = select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == safe_entry_id)
        normalized_email = self.normalize_email(email or "")
        if normalized_email:
            stmt = stmt.where(WarrantyEmailEntry.email == normalized_email)
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_warranty_email_entries_for_email(
        self,
        db_session: AsyncSession,
        email: str,
    ) -> List[WarrantyEmailEntry]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return []

        stmt = (
            select(WarrantyEmailEntry).where(WarrantyEmailEntry.email == normalized_email)
            .order_by(
                WarrantyEmailEntry.updated_at.desc(),
                WarrantyEmailEntry.created_at.desc(),
                WarrantyEmailEntry.id.desc(),
            )
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def find_warranty_email_entry_for_order(
        self,
        db_session: AsyncSession,
        email: str,
        entry_id: Optional[int] = None,
        code: Optional[str] = None,
        require_claimable: bool = False,
    ) -> Optional[WarrantyEmailEntry]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return None

        if entry_id:
            entry = await self.get_warranty_email_entry_by_id(
                db_session=db_session,
                entry_id=entry_id,
                email=normalized_email,
            )
            if entry and (not require_claimable or not self._get_warranty_entry_claim_error(entry)):
                return entry
            return None

        normalized_code = (code or "").strip()
        entries = await self.get_warranty_email_entries_for_email(db_session, normalized_email)
        if normalized_code:
            entries = [
                entry for entry in entries
                if (entry.last_redeem_code or "").strip() == normalized_code
            ]

        if require_claimable:
            entries = [
                entry for entry in entries
                if not self._get_warranty_entry_claim_error(entry)
            ]

        return entries[0] if entries else None

    async def list_warranty_email_entries(
        self,
        db_session: AsyncSession,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
        source_filter: Optional[str] = None,
        linked_team_status_filter: Optional[str] = None,
        remaining_claims_min: Optional[int] = None,
        remaining_claims_max: Optional[int] = None,
        remaining_days_min: Optional[int] = None,
        remaining_days_max: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        stmt = select(WarrantyEmailEntry)
        db_filters = []
        normalized_search = (search or "").strip()
        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            generated_code_entry_ids = (
                select(WarrantyEmailTemplateLock.generated_redeem_code_entry_id)
                .where(
                    WarrantyEmailTemplateLock.generated_redeem_code.ilike(search_pattern),
                    WarrantyEmailTemplateLock.generated_redeem_code_entry_id.isnot(None),
                )
            )
            search_filters = [
                WarrantyEmailEntry.email.ilike(search_pattern),
                WarrantyEmailEntry.last_redeem_code.ilike(search_pattern),
                WarrantyEmailEntry.id.in_(generated_code_entry_ids),
            ]
            db_filters.append(or_(*search_filters))

        normalized_source = (source_filter or "").strip().lower()
        if normalized_source in self.WARRANTY_EMAIL_SOURCE_LABELS:
            db_filters.append(func.coalesce(WarrantyEmailEntry.source, "auto_redeem") == normalized_source)

        if db_filters:
            stmt = stmt.where(and_(*db_filters))

        stmt = stmt.order_by(WarrantyEmailEntry.updated_at.desc(), WarrantyEmailEntry.created_at.desc())
        result = await db_session.execute(stmt)
        entry_models = list(result.scalars().all())
        team_ids = {
            int(entry.last_warranty_team_id)
            for entry in entry_models
            if entry.last_warranty_team_id
        }
        teams_by_id: Dict[int, Team] = {}
        if team_ids:
            team_result = await db_session.execute(
                select(Team).where(Team.id.in_(team_ids))
            )
            teams_by_id = {team.id: team for team in team_result.scalars().all()}
        generated_by_entry = await self._get_latest_generated_redeem_codes_by_entry(
            db_session,
            entry_models,
        )
        entries = [
            self.serialize_warranty_email_entry(
                entry,
                linked_team=teams_by_id.get(int(entry.last_warranty_team_id or 0)),
                generated_code=generated_by_entry.get(int(entry.id or 0)),
            )
            for entry in entry_models
        ]

        if normalized_search:
            entries = [
                entry
                for entry in entries
                if self._warranty_email_entry_matches_search(entry, normalized_search)
            ]

        normalized_status = (status_filter or "").strip().lower()
        if normalized_status in self.WARRANTY_EMAIL_STATUS_LABELS:
            entries = [entry for entry in entries if entry["status"] == normalized_status]

        normalized_linked_team_status = (linked_team_status_filter or "").strip().lower()
        if normalized_linked_team_status in self.TEAM_STATUS_LABELS:
            entries = [
                entry
                for entry in entries
                if (entry.get("last_warranty_team_status") or "no_record") == normalized_linked_team_status
            ]

        return [
            entry
            for entry in entries
            if self._warranty_entry_matches_remaining_filters(
                entry=entry,
                remaining_claims_min=remaining_claims_min,
                remaining_claims_max=remaining_claims_max,
                remaining_days_min=remaining_days_min,
                remaining_days_max=remaining_days_max,
            )
        ]

    def _serialize_warranty_email_order_entry(
        self,
        base_entry: Dict[str, Any],
        order: Dict[str, Any],
    ) -> Dict[str, Any]:
        warranty_info = order.get("warranty_info") or {}
        remaining_claims = int(warranty_info.get("remaining_claims") or 0)
        remaining_days = warranty_info.get("remaining_days")
        expires_at = warranty_info.get("expires_at")
        latest_team = order.get("latest_team") or {}

        if remaining_claims <= 0 and not expires_at:
            status = "inactive"
        elif remaining_claims <= 0:
            status = "claims_exhausted"
        elif remaining_days is None:
            status = "inactive"
        elif remaining_days <= 0:
            status = "expired"
        else:
            status = "active"

        return {
            **base_entry,
            "row_key": f"{base_entry.get('id')}:{order.get('code')}",
            "is_order_row": True,
            "last_redeem_code": order.get("code"),
            "transfer_redeem_code": order.get("transfer_redeem_code") or base_entry.get("transfer_redeem_code"),
            "transfer_redeem_code_remaining_days": (
                order.get("transfer_redeem_code_remaining_days")
                if order.get("transfer_redeem_code_remaining_days") is not None
                else base_entry.get("transfer_redeem_code_remaining_days")
            ),
            "transfer_redeem_code_generated_at": (
                order.get("transfer_redeem_code_generated_at")
                or base_entry.get("transfer_redeem_code_generated_at")
            ),
            "remaining_claims": remaining_claims,
            "remaining_days": remaining_days,
            "expires_at": expires_at,
            "status": status,
            "status_label": self.WARRANTY_EMAIL_STATUS_LABELS.get(status, "未知"),
            "last_warranty_team_id": latest_team.get("id") or base_entry.get("last_warranty_team_id"),
            "updated_at": (latest_team.get("redeemed_at") or base_entry.get("updated_at")),
            "warranty_order": order,
        }

    def _warranty_email_entry_matches_search(self, entry: Dict[str, Any], search: str) -> bool:
        normalized_search = (search or "").strip().lower()
        if not normalized_search:
            return True

        searchable_values = [
            entry.get("email"),
            entry.get("last_redeem_code"),
            entry.get("transfer_redeem_code"),
            entry.get("status_label"),
            entry.get("source_label"),
            entry.get("last_warranty_team_id"),
            entry.get("last_warranty_team_status_label"),
        ]
        return any(
            normalized_search in str(value or "").lower()
            for value in searchable_values
        )

    def _warranty_entry_matches_remaining_filters(
        self,
        entry: Dict[str, Any],
        remaining_claims_min: Optional[int] = None,
        remaining_claims_max: Optional[int] = None,
        remaining_days_min: Optional[int] = None,
        remaining_days_max: Optional[int] = None,
    ) -> bool:
        remaining_claims = entry.get("remaining_claims")
        remaining_days = entry.get("remaining_days")

        if remaining_claims_min is not None and remaining_claims < remaining_claims_min:
            return False
        if remaining_claims_max is not None and remaining_claims > remaining_claims_max:
            return False

        if remaining_days_min is not None or remaining_days_max is not None:
            if remaining_days is None:
                return False
            if remaining_days_min is not None and remaining_days < remaining_days_min:
                return False
            if remaining_days_max is not None and remaining_days > remaining_days_max:
                return False

        return True

    async def _find_warranty_entry_emails_by_redeem_code(
        self,
        db_session: AsyncSession,
        search_pattern: str
    ) -> set[str]:
        matched_emails: set[str] = set()

        code_result = await db_session.execute(
            select(RedemptionCode.used_by_email).where(
                RedemptionCode.used_by_email.is_not(None),
                RedemptionCode.code.ilike(search_pattern),
            )
        )
        matched_emails.update(
            self.normalize_email(email)
            for email in code_result.scalars().all()
            if email
        )

        record_result = await db_session.execute(
            select(RedemptionRecord.email).where(
                RedemptionRecord.code.ilike(search_pattern)
            )
        )
        matched_emails.update(
            self.normalize_email(email)
            for email in record_result.scalars().all()
            if email
        )

        return matched_emails

    async def save_warranty_email_entry(
        self,
        db_session: AsyncSession,
        email: str,
        remaining_claims: int,
        remaining_days: Optional[int],
        remaining_seconds: Optional[int] = None,
        source: str = "manual",
        entry_id: Optional[int] = None
    ) -> WarrantyEmailEntry:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            raise ValueError("邮箱不能为空")

        remaining_claims_int = self._normalize_remaining_claims(remaining_claims)
        expires_at = self._build_warranty_entry_expires_at(remaining_days, remaining_seconds)

        current_entry = None
        if entry_id is not None:
            result = await db_session.execute(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == entry_id)
            )
            current_entry = result.scalar_one_or_none()
            if not current_entry:
                raise ValueError("质保邮箱记录不存在")

        target_entry = current_entry
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

    def _normalize_remaining_claims(self, remaining_claims: int) -> int:
        try:
            remaining_claims_int = int(remaining_claims)
        except (TypeError, ValueError):
            raise ValueError("剩余次数必须是非负整数")

        if remaining_claims_int < 0:
            raise ValueError("剩余次数必须是非负整数")

        return remaining_claims_int

    async def save_warranty_email_order_entry(
        self,
        db_session: AsyncSession,
        email: str,
        redeem_code: str,
        remaining_claims: int,
        remaining_days: Optional[int],
        remaining_seconds: Optional[int] = None,
        source: str = "manual",
        entry_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            raise ValueError("邮箱不能为空")

        normalized_code = (redeem_code or "").strip()
        if not normalized_code:
            raise ValueError("质保兑换码不能为空")

        warranty_entry = None
        if entry_id is not None:
            result = await db_session.execute(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.id == entry_id)
            )
            warranty_entry = result.scalar_one_or_none()
            if not warranty_entry:
                raise ValueError("质保邮箱记录不存在")
            if self.normalize_email(warranty_entry.email) != normalized_email:
                raise ValueError("质保订单编辑不支持变更邮箱，请清空表单后新增记录")
        else:
            warranty_entry = await self.find_warranty_email_entry_for_order(
                db_session=db_session,
                email=normalized_email,
                code=normalized_code,
            )

        entry = await self.save_warranty_email_entry(
            db_session=db_session,
            entry_id=warranty_entry.id if warranty_entry else entry_id,
            email=normalized_email,
            remaining_days=remaining_days,
            remaining_seconds=remaining_seconds,
            remaining_claims=remaining_claims,
            source=source,
        )
        entry.last_redeem_code = normalized_code
        await db_session.commit()
        await db_session.refresh(entry)
        return self.serialize_warranty_email_entry(entry)

    async def bulk_update_warranty_email_entries(
        self,
        db_session: AsyncSession,
        entry_ids: List[int],
        update_remaining_days: bool = False,
        remaining_days: Optional[int] = None,
        update_remaining_claims: bool = False,
        remaining_claims: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized_ids = self._normalize_warranty_entry_ids(entry_ids)
        if not normalized_ids:
            raise ValueError("请先选择要修改的质保邮箱")

        if not update_remaining_days and not update_remaining_claims:
            raise ValueError("请至少选择一个要批量修改的字段")

        expires_at = None
        if update_remaining_days:
            if remaining_days is None:
                raise ValueError("请填写剩余天数")
            expires_at = self._build_warranty_entry_expires_at(remaining_days)

        remaining_claims_int = None
        if update_remaining_claims:
            if remaining_claims is None:
                raise ValueError("请填写剩余次数")
            try:
                remaining_claims_int = int(remaining_claims)
            except (TypeError, ValueError) as exc:
                raise ValueError("剩余次数必须是非负整数") from exc
            if remaining_claims_int < 0:
                raise ValueError("剩余次数必须是非负整数")

        result = await db_session.execute(
            select(WarrantyEmailEntry).where(WarrantyEmailEntry.id.in_(normalized_ids))
        )
        entries = result.scalars().all()
        if not entries:
            raise ValueError("未找到可更新的质保邮箱记录")

        for entry in entries:
            if update_remaining_days:
                entry.expires_at = expires_at
            if update_remaining_claims:
                entry.remaining_claims = remaining_claims_int

        await db_session.commit()
        return {
            "requested_count": len(normalized_ids),
            "updated_count": len(entries),
        }

    async def bulk_delete_warranty_email_entries(
        self,
        db_session: AsyncSession,
        entry_ids: List[int],
    ) -> Dict[str, Any]:
        normalized_ids = self._normalize_warranty_entry_ids(entry_ids)
        if not normalized_ids:
            raise ValueError("请先选择要删除的质保邮箱")

        result = await db_session.execute(
            select(WarrantyEmailEntry).where(WarrantyEmailEntry.id.in_(normalized_ids))
        )
        entries = result.scalars().all()
        if not entries:
            raise ValueError("未找到可删除的质保邮箱记录")

        for entry in entries:
            await db_session.delete(entry)

        await db_session.commit()
        return {
            "requested_count": len(normalized_ids),
            "deleted_count": len(entries),
        }

    def _normalize_warranty_entry_ids(self, entry_ids: List[int]) -> List[int]:
        normalized_ids = []
        for entry_id in entry_ids or []:
            try:
                entry_id_int = int(entry_id)
            except (TypeError, ValueError):
                continue
            if entry_id_int > 0:
                normalized_ids.append(entry_id_int)

        return list(dict.fromkeys(normalized_ids))

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
        has_warranty_code: Optional[bool] = None,
        team_id: Optional[int] = None,
    ) -> Optional[WarrantyEmailEntry]:
        code_result = await db_session.execute(
            select(RedemptionCode).where(RedemptionCode.code == redeem_code)
        )
        redemption_code = code_result.scalar_one_or_none()
        resolved_has_warranty_code = (
            bool(redemption_code.has_warranty)
            if redemption_code is not None
            else bool(has_warranty_code)
        )

        if not resolved_has_warranty_code:
            return None

        normalized_email = self.normalize_email(email)
        result = await db_session.execute(
            select(WarrantyEmailEntry)
            .where(
                WarrantyEmailEntry.email == normalized_email,
                WarrantyEmailEntry.last_redeem_code == redeem_code,
                func.coalesce(WarrantyEmailEntry.source, "auto_redeem") == "auto_redeem",
            )
            .order_by(WarrantyEmailEntry.updated_at.desc(), WarrantyEmailEntry.id.desc())
        )
        entry = result.scalars().first()
        warranty_seconds = (
            getattr(redemption_code, "warranty_seconds", None)
            if redemption_code is not None
            else None
        )
        warranty_days = (
            redemption_code.warranty_days
            if redemption_code is not None and redemption_code.warranty_days is not None
            else self.AUTO_WARRANTY_ENTRY_DEFAULT_DAYS
        )
        warranty_claims = (
            redemption_code.warranty_claims
            if redemption_code is not None and redemption_code.warranty_claims is not None
            else self.AUTO_WARRANTY_ENTRY_DEFAULT_CLAIMS
        )
        warranty_claims = max(int(warranty_claims or 0), 0)
        default_expires_at = self._build_warranty_entry_expires_at(warranty_days, warranty_seconds)

        if entry:
            entry.last_redeem_code = redeem_code
            entry.remaining_claims = warranty_claims
            entry.expires_at = default_expires_at
            if team_id:
                entry.last_warranty_team_id = int(team_id)
            entry.updated_at = get_now()
        else:
            entry = WarrantyEmailEntry(
                email=normalized_email,
                remaining_claims=warranty_claims,
                expires_at=default_expires_at,
                source="auto_redeem",
                last_redeem_code=redeem_code,
                last_warranty_team_id=int(team_id) if team_id else None,
            )
            db_session.add(entry)

        await db_session.flush()
        return entry

    async def _consume_warranty_claim(
        self,
        db_session: AsyncSession,
        entry: Optional[WarrantyEmailEntry]
    ) -> None:
        if not entry:
            await db_session.commit()
            return
        entry.remaining_claims = max(int(entry.remaining_claims or 0) - 1, 0)
        await db_session.commit()
        await db_session.refresh(entry)

    async def _record_warranty_claim_success(
        self,
        db_session: AsyncSession,
        entry: Optional[WarrantyEmailEntry],
        email: str,
        team: Team,
        redeem_code: Optional[str] = None,
    ) -> None:
        if entry:
            entry.last_warranty_team_id = team.id

        record_code = (redeem_code or (entry.last_redeem_code if entry else "") or "").strip()
        if record_code:
            code_exists_result = await db_session.execute(
                select(RedemptionCode.code).where(RedemptionCode.code == record_code)
            )
            if code_exists_result.scalar_one_or_none():
                db_session.add(
                    RedemptionRecord(
                        email=self.normalize_email(email),
                        code=record_code,
                        team_id=team.id,
                        account_id=team.account_id,
                        is_warranty_redemption=True,
                        warranty_super_code_type=None
                    )
                )
            else:
                logger.warning(
                    "质保成功但兑换码不存在，跳过使用记录写入 email=%s code=%s",
                    self.normalize_email(email),
                    record_code,
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

        previous_team_status = (latest_team.status or "").strip().lower()
        try:
            sync_result = await self.team_service.refresh_team_state(
                latest_team.id,
                db_session,
                source=SOURCE_USER_WARRANTY,
            )
            if not sync_result.get("success"):
                latest_team_status = (latest_team.status or "").strip().lower()
                team_became_banned_during_refresh = (
                    previous_team_status != "banned"
                    and latest_team_status == "banned"
                )
                if (
                    sync_result.get("error_code") in self.team_service.BANNED_ERROR_CODES
                    or team_became_banned_during_refresh
                ):
                    logger.info(
                        "质保状态查询识别到 Team 已不可用，按封禁处理 email=%s team_id=%s error_code=%s previous_status=%s current_status=%s",
                        self.normalize_email(email),
                        latest_team.id,
                        sync_result.get("error_code"),
                        previous_team_status,
                        latest_team_status
                    )
                    if latest_team_status != "banned":
                        latest_team.status = "banned"
                    await db_session.commit()
                    refreshed_context = await self._load_latest_team_context_for_email(
                        db_session,
                        email,
                        warranty_entry=warranty_entry
                    )
                    return refreshed_context or latest_context

                logger.warning(
                    "质保状态查询刷新最近 Team 失败 email=%s team_id=%s error=%s",
                    self.normalize_email(email),
                    latest_team.id,
                    sync_result.get("error")
                )
                raise RuntimeError(sync_result.get("error") or "实时刷新最近 Team 状态失败，请稍后重试")
            await db_session.commit()
        except Exception as exc:
            logger.warning(
                "质保状态查询刷新最近 Team 异常 email=%s team_id=%s error=%s",
                self.normalize_email(email),
                latest_team.id,
                exc
            )
            error_message = str(exc) or "实时刷新最近 Team 状态失败，请稍后重试"
            raise RuntimeError(error_message) from exc

        refreshed_context = await self._load_latest_team_context_for_email(
            db_session,
            email,
            warranty_entry=warranty_entry
        )
        if refreshed_context:
            return refreshed_context

        raise RuntimeError("实时刷新成功，但未找到最新 Team 状态，请稍后重试")

    async def _refresh_warranty_entry_team_context(
        self,
        db_session: AsyncSession,
        email: str,
        warranty_entry: Optional[WarrantyEmailEntry],
    ) -> Optional[Dict[str, Any]]:
        latest_context = await self._load_latest_team_context_from_warranty_entry(
            db_session,
            warranty_entry,
        )
        if not latest_context:
            return None

        latest_team = latest_context.get("team")
        if not latest_team:
            return latest_context

        previous_team_status = (latest_team.status or "").strip().lower()
        try:
            sync_result = await self.team_service.refresh_team_state(
                latest_team.id,
                db_session,
                source=SOURCE_USER_WARRANTY,
            )
            if not sync_result.get("success"):
                latest_team_status = (latest_team.status or "").strip().lower()
                team_became_banned_during_refresh = (
                    previous_team_status != "banned"
                    and latest_team_status == "banned"
                )
                if (
                    sync_result.get("error_code") in self.team_service.BANNED_ERROR_CODES
                    or team_became_banned_during_refresh
                ):
                    if latest_team_status != "banned":
                        latest_team.status = "banned"
                    await db_session.commit()
                    refreshed_context = await self._load_latest_team_context_from_warranty_entry(
                        db_session,
                        warranty_entry,
                    )
                    return refreshed_context or latest_context

                raise RuntimeError(sync_result.get("error") or "实时刷新订单 Team 状态失败，请稍后重试")
            await db_session.commit()
        except Exception as exc:
            logger.warning(
                "质保订单关联 Team 刷新异常 email=%s entry_id=%s team_id=%s error=%s",
                self.normalize_email(email),
                getattr(warranty_entry, "id", None),
                latest_team.id,
                exc,
            )
            raise RuntimeError(str(exc) or "实时刷新订单 Team 状态失败，请稍后重试") from exc

        refreshed_context = await self._load_latest_team_context_from_warranty_entry(
            db_session,
            warranty_entry,
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

    def _serialize_redemption_code_team_info(
        self,
        redemption_code: RedemptionCode,
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
            "redeemed_at": redemption_code.used_at.isoformat() if redemption_code and redemption_code.used_at else None,
            "expires_at": team.expires_at.isoformat() if team and team.expires_at else None,
            "code": redemption_code.code if redemption_code else None,
            "is_warranty_redemption": False,
        }

    def _calculate_remaining_seconds(self, expires_at: Optional[datetime]) -> Optional[int]:
        if not expires_at:
            return None

        return max(int((expires_at - get_now()).total_seconds()), 0)

    def _calculate_remaining_days(self, expires_at: Optional[datetime]) -> Optional[int]:
        remaining_seconds = self._calculate_remaining_seconds(expires_at)
        if remaining_seconds is None:
            return None
        if remaining_seconds <= 0:
            return 0
        return max(math.ceil(remaining_seconds / 86400), 0)

    def format_remaining_seconds(self, remaining_seconds: Optional[int]) -> Optional[str]:
        if remaining_seconds is None:
            return None

        total_seconds = max(int(remaining_seconds), 0)
        days, day_remainder = divmod(total_seconds, 86400)
        hours, hour_remainder = divmod(day_remainder, 3600)
        minutes, seconds = divmod(hour_remainder, 60)
        return f"{days}天 {hours:02d}:{minutes:02d}:{seconds:02d}"

    def _format_remaining_seconds(self, remaining_seconds: Optional[int]) -> Optional[str]:
        return self.format_remaining_seconds(remaining_seconds)

    def _get_warranty_entry_claim_error(
        self,
        entry: Optional[WarrantyEmailEntry],
        subject: str = "该邮箱",
    ) -> Optional[str]:
        if not entry:
            return "该邮箱不在质保邮箱列表中"

        if int(entry.remaining_claims or 0) <= 0:
            return f"{subject}暂无可用质保次数"

        if not entry.expires_at:
            return f"{subject}质保资格未启用"

        if entry.expires_at <= get_now():
            return f"{subject}质保资格已过期"

        return None

    def _is_latest_team_banned(
        self,
        latest_team_info: Optional[Dict[str, Any]],
    ) -> bool:
        latest_status = ((latest_team_info or {}).get("status") or "").strip().lower()
        return latest_status == "banned"

    def _build_latest_team_not_banned_message(
        self,
        latest_team_info: Optional[Dict[str, Any]],
        subject: str = "该质保订单",
    ) -> str:
        if not latest_team_info:
            return f"未找到{subject}对应邮箱最近加入的 Team，暂不能提交质保。"

        latest_status = (latest_team_info.get("status") or "").strip().lower()
        status_label = "封禁" if latest_status == "banned" else "可用"
        return f"{subject}最近加入的 Team 当前状态为「{status_label}」，只有封禁状态才可以提交质保。"

    def _get_warranty_order_display_code(
        self,
        entry: WarrantyEmailEntry,
        code: Optional[str] = None,
    ) -> str:
        order_code = (code or entry.last_redeem_code or "").strip()
        if order_code:
            return order_code

        source = (entry.source or "").strip().lower()
        if source == "manual":
            return "管理员手动维护"

        return "未绑定兑换码"

    def _serialize_warranty_entry_order(
        self,
        entry: WarrantyEmailEntry,
        code: Optional[str] = None,
        latest_team_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        warranty_info = self.serialize_warranty_email_entry(entry)
        order_code = (code or entry.last_redeem_code or "").strip()
        remaining_claims = int(warranty_info.get("remaining_claims") or 0)
        remaining_days = warranty_info.get("remaining_days")
        remaining_seconds = warranty_info.get("remaining_seconds")
        remaining_time = warranty_info.get("remaining_time")
        warranty_valid = warranty_info.get("status") == "active"
        latest_team_banned = self._is_latest_team_banned(latest_team_info)
        status_checked = latest_team_info is not None
        can_claim = bool(warranty_valid and status_checked and latest_team_banned)

        if can_claim:
            message = "该质保订单最近加入的 Team 已封禁，可以提交质保。"
        elif warranty_valid and status_checked:
            message = self._build_latest_team_not_banned_message(latest_team_info)
        elif warranty_valid:
            message = "质保订单已查询到，请继续查询该订单对应邮箱上次加入的 Team 状态。"
        else:
            message = "该邮箱质保资格不可用，请确认剩余次数和剩余天数。"

        return {
            "entry_id": entry.id,
            "code": order_code,
            "display_code": self._get_warranty_order_display_code(entry, order_code),
            "has_warranty": True,
            "source": warranty_info.get("source"),
            "source_label": warranty_info.get("source_label"),
            "can_claim": can_claim,
            "can_refresh_status": bool(warranty_valid),
            "status_checked": status_checked,
            "warranty_valid": bool(warranty_valid),
            "remaining_claims": remaining_claims,
            "remaining_days": remaining_days,
            "remaining_seconds": remaining_seconds,
            "remaining_time": remaining_time,
            "warranty_expires_at": warranty_info.get("expires_at"),
            "used_claims": None,
            "total_claims": None,
            "latest_team": latest_team_info,
            "warranty_info": warranty_info,
            "message": message,
        }

    def _get_order_initial_claims(
        self,
        redemption_code: RedemptionCode,
        warranty_entry: Optional[WarrantyEmailEntry] = None,
        is_legacy_entry_code: bool = False,
    ) -> int:
        if redemption_code and redemption_code.has_warranty:
            claim_value = (
                redemption_code.warranty_claims
                if redemption_code.warranty_claims is not None
                else self.AUTO_WARRANTY_ENTRY_DEFAULT_CLAIMS
            )
            return max(int(claim_value), 0)
        if is_legacy_entry_code and warranty_entry:
            return max(int(warranty_entry.remaining_claims or 0), 0)
        return self.AUTO_WARRANTY_ENTRY_DEFAULT_CLAIMS

    def _get_order_expires_at(
        self,
        redemption_code: RedemptionCode,
        first_used_at: Optional[datetime],
        warranty_entry: Optional[WarrantyEmailEntry] = None,
        is_legacy_entry_code: bool = False,
    ) -> Optional[datetime]:
        if redemption_code and redemption_code.has_warranty:
            if redemption_code.warranty_expires_at:
                return redemption_code.warranty_expires_at
            start_at = redemption_code.used_at or first_used_at
            if start_at:
                seconds = getattr(redemption_code, "warranty_seconds", None)
                if seconds is not None:
                    return start_at + timedelta(seconds=max(int(seconds or 0), 0))
                days = (
                    redemption_code.warranty_days
                    if redemption_code.warranty_days is not None
                    else self.AUTO_WARRANTY_ENTRY_DEFAULT_DAYS
                )
                return start_at + timedelta(days=days)
        if is_legacy_entry_code and warranty_entry:
            return warranty_entry.expires_at
        return None

    async def _load_warranty_order_contexts_for_email(
        self,
        db_session: AsyncSession,
        email: str,
        warranty_entry: Optional[WarrantyEmailEntry] = None,
        target_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_email = self.normalize_email(email)
        normalized_code = (target_code or "").strip()
        if not normalized_email:
            return []

        legacy_code = (warranty_entry.last_redeem_code or "").strip() if warranty_entry else ""
        code_filters = [RedemptionCode.has_warranty.is_(True)]
        if legacy_code:
            code_filters.append(RedemptionRecord.code == legacy_code)

        stmt = (
            select(RedemptionRecord, RedemptionCode, Team)
            .join(RedemptionCode, RedemptionRecord.code == RedemptionCode.code)
            .join(Team, RedemptionRecord.team_id == Team.id)
            .where(
                func.lower(RedemptionRecord.email) == normalized_email,
                or_(*code_filters),
            )
            .order_by(RedemptionRecord.redeemed_at.desc(), RedemptionRecord.id.desc())
        )
        if normalized_code:
            stmt = stmt.where(RedemptionRecord.code == normalized_code)

        result = await db_session.execute(stmt)
        order_map: Dict[str, Dict[str, Any]] = {}
        for record, redemption_code, team in result.all():
            code_key = (record.code or "").strip()
            if not code_key:
                continue

            context = order_map.setdefault(
                code_key,
                {
                    "code": code_key,
                    "redemption_code": redemption_code,
                    "latest_record": None,
                    "team": None,
                    "used_claims": 0,
                    "first_used_at": None,
                    "latest_at": None,
                    "is_legacy_entry_code": bool(legacy_code and code_key == legacy_code and not redemption_code.has_warranty),
                }
            )

            if not context["latest_record"]:
                context["latest_record"] = record
                context["team"] = team
                context["latest_at"] = record.redeemed_at

            if bool(record.is_warranty_redemption):
                context["used_claims"] += 1

            if not bool(record.is_warranty_redemption):
                first_used_at = context["first_used_at"]
                if not first_used_at or (record.redeemed_at and record.redeemed_at < first_used_at):
                    context["first_used_at"] = record.redeemed_at

        code_stmt = (
            select(RedemptionCode, Team)
            .join(Team, RedemptionCode.used_team_id == Team.id)
            .where(
                func.lower(RedemptionCode.used_by_email) == normalized_email,
                RedemptionCode.has_warranty.is_(True),
                RedemptionCode.used_team_id.is_not(None),
            )
            .order_by(RedemptionCode.used_at.desc(), RedemptionCode.id.desc())
        )
        if normalized_code:
            code_stmt = code_stmt.where(RedemptionCode.code == normalized_code)

        code_result = await db_session.execute(code_stmt)
        for redemption_code, team in code_result.all():
            code_key = (redemption_code.code or "").strip()
            if not code_key or code_key in order_map:
                continue
            order_map[code_key] = {
                "code": code_key,
                "redemption_code": redemption_code,
                "latest_record": None,
                "team": team,
                "used_claims": 0,
                "first_used_at": redemption_code.used_at,
                "latest_at": redemption_code.used_at,
                "is_legacy_entry_code": False,
            }

        contexts = list(order_map.values())
        contexts.sort(
            key=lambda item: (
                item.get("latest_at") or datetime.min,
                item["latest_record"].id if item.get("latest_record") else 0,
            ),
            reverse=True,
        )
        legacy_entry_context = None
        if warranty_entry and warranty_entry.last_warranty_team_id:
            legacy_entry_context = await self._load_latest_team_context_from_warranty_entry(
                db_session,
                warranty_entry,
            )
        for context in contexts:
            if context.get("is_legacy_entry_code") and legacy_entry_context:
                context["team"] = legacy_entry_context.get("team")
                context["team_info"] = legacy_entry_context.get("team_info")
                if legacy_entry_context.get("record"):
                    context["latest_record"] = legacy_entry_context.get("record")
                    context["latest_at"] = legacy_entry_context["record"].redeemed_at
            else:
                if context.get("latest_record"):
                    context["team_info"] = self._serialize_latest_team_info(
                        context["latest_record"],
                        context["team"],
                    )
                else:
                    context["team_info"] = self._serialize_redemption_code_team_info(
                        context["redemption_code"],
                        context["team"],
                    )
        return contexts

    async def _refresh_warranty_order_context_for_email(
        self,
        db_session: AsyncSession,
        email: str,
        code: str,
        warranty_entry: Optional[WarrantyEmailEntry] = None,
    ) -> Optional[Dict[str, Any]]:
        contexts = await self._load_warranty_order_contexts_for_email(
            db_session,
            email,
            warranty_entry=warranty_entry,
            target_code=code,
        )
        if not contexts:
            return None

        latest_context = contexts[0]
        latest_team = latest_context.get("team")
        if not latest_team:
            return latest_context

        previous_team_status = (latest_team.status or "").strip().lower()
        try:
            sync_result = await self.team_service.refresh_team_state(
                latest_team.id,
                db_session,
                source=SOURCE_USER_WARRANTY,
            )
            if not sync_result.get("success"):
                latest_team_status = (latest_team.status or "").strip().lower()
                team_became_banned_during_refresh = (
                    previous_team_status != "banned"
                    and latest_team_status == "banned"
                )
                if (
                    sync_result.get("error_code") in self.team_service.BANNED_ERROR_CODES
                    or team_became_banned_during_refresh
                ):
                    if latest_team_status != "banned":
                        latest_team.status = "banned"
                    await db_session.commit()
                    refreshed_contexts = await self._load_warranty_order_contexts_for_email(
                        db_session,
                        email,
                        warranty_entry=warranty_entry,
                        target_code=code,
                    )
                    return refreshed_contexts[0] if refreshed_contexts else latest_context

                raise RuntimeError(sync_result.get("error") or "实时刷新订单 Team 状态失败，请稍后重试")
            await db_session.commit()
        except Exception as exc:
            logger.warning(
                "质保订单状态刷新异常 email=%s code=%s team_id=%s error=%s",
                self.normalize_email(email),
                code,
                latest_team.id,
                exc
            )
            raise RuntimeError(str(exc) or "实时刷新订单 Team 状态失败，请稍后重试") from exc

        refreshed_contexts = await self._load_warranty_order_contexts_for_email(
            db_session,
            email,
            warranty_entry=warranty_entry,
            target_code=code,
        )
        return refreshed_contexts[0] if refreshed_contexts else latest_context

    def _serialize_warranty_order_context(
        self,
        context: Dict[str, Any],
        warranty_entry: Optional[WarrantyEmailEntry] = None,
    ) -> Dict[str, Any]:
        redemption_code = context["redemption_code"]
        initial_claims = self._get_order_initial_claims(
            redemption_code,
            warranty_entry=warranty_entry,
            is_legacy_entry_code=bool(context.get("is_legacy_entry_code")),
        )
        used_claims = max(int(context.get("used_claims") or 0), 0)
        remaining_claims = max(initial_claims - used_claims, 0)
        expires_at = self._get_order_expires_at(
            redemption_code,
            context.get("first_used_at"),
            warranty_entry=warranty_entry,
            is_legacy_entry_code=bool(context.get("is_legacy_entry_code")),
        )
        remaining_seconds = self._calculate_remaining_seconds(expires_at)
        remaining_days = self._calculate_remaining_days(expires_at)
        remaining_time = self._format_remaining_seconds(remaining_seconds)
        entry_info = (
            self.serialize_warranty_email_entry(warranty_entry)
            if warranty_entry
            else None
        )
        if entry_info:
            remaining_claims = int(entry_info.get("remaining_claims") or 0)
            remaining_days = entry_info.get("remaining_days")
            remaining_seconds = entry_info.get("remaining_seconds")
            remaining_time = entry_info.get("remaining_time")
            warranty_valid = entry_info.get("status") == "active"
            warranty_expires_at = entry_info.get("expires_at")
        else:
            warranty_valid = remaining_claims > 0 and bool(expires_at) and expires_at > get_now()
            warranty_expires_at = expires_at.isoformat() if expires_at else None
        latest_team_info = context.get("team_info")
        latest_team_banned = self._is_latest_team_banned(latest_team_info)
        can_claim = bool(warranty_valid and latest_team_banned)

        if can_claim:
            message = "该质保订单最近加入的 Team 已封禁，可以提交质保。"
        elif warranty_valid:
            message = self._build_latest_team_not_banned_message(latest_team_info)
        elif not warranty_valid and remaining_claims <= 0:
            message = "该质保订单暂无可用质保次数。"
        elif not warranty_valid:
            message = "该质保订单质保资格已过期或未启用。"
        else:
            message = self._build_latest_team_not_banned_message(latest_team_info)

        warranty_info = {
            "remaining_claims": remaining_claims,
            "remaining_days": remaining_days,
            "remaining_seconds": remaining_seconds,
            "remaining_time": remaining_time,
            "expires_at": warranty_expires_at,
            "used_claims": used_claims,
            "total_claims": initial_claims,
        }
        return {
            "entry_id": getattr(warranty_entry, "id", None),
            "code": context["code"],
            "display_code": self._get_warranty_order_display_code(
                warranty_entry,
                context["code"],
            ) if warranty_entry else context["code"],
            "has_warranty": bool(redemption_code.has_warranty),
            "source": getattr(warranty_entry, "source", None),
            "source_label": self.WARRANTY_EMAIL_SOURCE_LABELS.get(
                getattr(warranty_entry, "source", None),
                "未知",
            ),
            "can_claim": can_claim,
            "can_refresh_status": bool(warranty_valid),
            "status_checked": latest_team_info is not None,
            "warranty_valid": warranty_valid,
            "remaining_claims": remaining_claims,
            "remaining_days": remaining_days,
            "remaining_seconds": remaining_seconds,
            "remaining_time": remaining_time,
            "warranty_expires_at": warranty_expires_at,
            "used_claims": used_claims,
            "total_claims": initial_claims,
            "latest_team": latest_team_info,
            "warranty_info": warranty_info,
            "message": message,
        }

    async def get_warranty_order_info(
        self,
        db_session: AsyncSession,
        email: str,
        code: str,
        warranty_entry: Optional[WarrantyEmailEntry] = None,
    ) -> Optional[Dict[str, Any]]:
        entry = warranty_entry
        if not entry:
            entry = await self.find_warranty_email_entry_for_order(
                db_session=db_session,
                email=email,
                code=code,
            )
        if not entry:
            return None

        contexts = await self._load_warranty_order_contexts_for_email(
            db_session,
            email,
            warranty_entry=entry,
            target_code=code,
        )
        if contexts:
            return self._serialize_warranty_order_context(contexts[0], entry)

        latest_context = await self._load_latest_team_context_for_email(
            db_session,
            email,
            warranty_entry=entry,
        )
        return self._serialize_warranty_entry_order(
            entry,
            code=code,
            latest_team_info=latest_context.get("team_info") if latest_context else None,
        )

    async def refresh_warranty_order_status(
        self,
        db_session: AsyncSession,
        email: str,
        entry_id: Optional[int],
        code: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}

        warranty_entry = await self.find_warranty_email_entry_for_order(
            db_session=db_session,
            email=normalized_email,
            entry_id=entry_id,
            code=(code or "").strip() or None,
        )
        if not warranty_entry:
            return {"success": False, "error": "未找到该邮箱绑定的质保订单"}

        entry_error = self._get_warranty_entry_claim_error(warranty_entry, subject="该质保订单")
        if entry_error:
            return {"success": False, "error": entry_error}

        selected_code = ((code or "").strip() or (warranty_entry.last_redeem_code or "").strip())
        latest_context = None

        try:
            latest_context = await self._refresh_warranty_entry_team_context(
                db_session=db_session,
                email=normalized_email,
                warranty_entry=warranty_entry,
            )

            if not latest_context and selected_code:
                latest_context = await self._refresh_warranty_order_context_for_email(
                    db_session=db_session,
                    email=normalized_email,
                    code=selected_code,
                    warranty_entry=warranty_entry,
                )
        except Exception as exc:
            logger.warning(
                "质保订单 Team 状态刷新失败 email=%s entry_id=%s code=%s error=%s",
                normalized_email,
                getattr(warranty_entry, "id", entry_id),
                selected_code,
                exc,
            )
            return {
                "success": False,
                "error": str(exc) or "实时刷新订单 Team 状态失败，请稍后重试",
            }

        latest_team_info = latest_context.get("team_info") if latest_context else None
        if not latest_team_info:
            return {
                "success": False,
                "error": "未找到该质保订单对应邮箱最近加入的 Team，暂不能提交质保。"
            }

        order = self._serialize_warranty_entry_order(
            warranty_entry,
            code=selected_code or None,
            latest_team_info=latest_team_info,
        )
        return {
            "success": True,
            "email": normalized_email,
            "can_claim": bool(order.get("can_claim")),
            "latest_team": order.get("latest_team"),
            "warranty_info": order.get("warranty_info"),
            "warranty_order": order,
            "message": order.get("message"),
            "error": None,
        }

    async def get_warranty_claim_status(
        self,
        db_session: AsyncSession,
        email: str
    ) -> Dict[str, Any]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}

        warranty_entries = await self.get_warranty_email_entries_for_email(db_session, normalized_email)
        if not warranty_entries:
            return {"success": False, "error": "该邮箱不在质保邮箱列表中"}

        warranty_orders: List[Dict[str, Any]] = []
        for warranty_entry in warranty_entries:
            order_code = (warranty_entry.last_redeem_code or "").strip()
            warranty_orders.append(
                self._serialize_warranty_entry_order(
                    warranty_entry,
                    code=order_code or None,
                    latest_team_info=None,
                )
            )

        can_claim = False
        refreshable_count = sum(1 for order in warranty_orders if order.get("can_refresh_status"))
        if refreshable_count > 0:
            message = f"已查询到 {len(warranty_orders)} 个质保订单，请对仍有剩余次数和天数的订单单独查询 Team 状态。"
        else:
            message = f"已查询到 {len(warranty_orders)} 个质保订单，但当前没有剩余次数和天数均可用的订单。"

        return {
            "success": True,
            "email": normalized_email,
            "can_claim": can_claim,
            "latest_team": None,
            "warranty_info": warranty_orders[0].get("warranty_info") if warranty_orders else None,
            "warranty_orders": warranty_orders,
            "message": message
        }

    async def check_warranty_email_membership(
        self,
        db_session: AsyncSession,
        email: str,
        warranty_code: Optional[str] = None,
        match_templates: Optional[List[Dict[str, Any]]] = None,
        miss_templates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        判定邮箱与质保兑换码是否共同命中质保邮箱列表，并为首次查询邮箱随机锁定展示模板。
        """
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}

        normalized_code = (warranty_code or "").strip()
        if not normalized_code:
            return {"success": False, "error": "质保兑换码不能为空"}

        entries = await self.get_warranty_email_entries_for_email(
            db_session,
            normalized_email
        )
        entries_with_code = [
            entry for entry in entries
            if (entry.last_redeem_code or "").strip()
        ]
        entries_without_code = [
            entry for entry in entries
            if not (entry.last_redeem_code or "").strip()
        ]
        selected_entry = next(
            (
                entry for entry in entries_with_code
                if (entry.last_redeem_code or "").strip() == normalized_code
            ),
            None,
        )
        super_code_matched = False
        if selected_entry is None and entries_without_code:
            super_code_matched = await settings_service.match_warranty_email_check_super_code(
                db_session,
                normalized_code,
            )
            if super_code_matched:
                selected_entry = entries_without_code[0]

        has_missing_code = bool(entries) and not entries_with_code and selected_entry is None
        has_wrong_code = bool(entries_with_code) and selected_entry is None
        matched = selected_entry is not None
        template_matched = matched
        templates = match_templates if template_matched else miss_templates
        template_lock = await self._get_or_create_warranty_email_template_lock(
            db_session=db_session,
            email=normalized_email,
            matched=template_matched,
            templates=templates or [],
        )
        usable_linked_team = (
            await self._get_usable_linked_team_for_warranty_entries(db_session, [selected_entry])
            if selected_entry
            else None
        )
        message = None
        if has_missing_code:
            message = self.WARRANTY_EMAIL_MISSING_REDEEM_CODE_MESSAGE
        elif has_wrong_code:
            message = self.WARRANTY_EMAIL_WRONG_REDEEM_CODE_MESSAGE
        elif usable_linked_team is not None:
            message = self.TEAM_AVAILABLE_NO_WARRANTY_MESSAGE

        return {
            "success": True,
            "email": normalized_email,
            "matched": matched,
            "matched_count": 1 if selected_entry else 0,
            "code_required": True,
            "warranty_code": normalized_code,
            "super_code_matched": super_code_matched,
            "email_found": bool(entries),
            "email_has_redeem_code": bool(entries_with_code),
            "missing_redeem_code": has_missing_code,
            "wrong_redeem_code": has_wrong_code,
            "skip_redeem_code_generation": usable_linked_team is not None or has_missing_code or has_wrong_code,
            "usable_linked_team": usable_linked_team,
            "message": message,
            "template_key": template_lock.template_key if template_lock else None,
            "template_matched": bool(template_lock.matched) if template_lock else template_matched,
            "template_lock": template_lock,
            "selected_entry": selected_entry,
            "generated_redeem_code": (
                template_lock.generated_redeem_code
                if matched and template_lock and template_lock.generated_redeem_code
                else None
            ),
            "generated_redeem_code_remaining_days": (
                template_lock.generated_redeem_code_remaining_days
                if matched and template_lock
                else None
            ),
        }

    async def ensure_warranty_email_check_redeem_code(
        self,
        db_session: AsyncSession,
        *,
        email: str,
        user_id: Optional[int] = None,
        template_lock: Optional[WarrantyEmailTemplateLock] = None,
        warranty_entry: Optional[WarrantyEmailEntry] = None,
        sub2api_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """为命中质保邮箱列表的查询生成并持久化 Sub2API 订阅兑换码。"""
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}

        try:
            safe_user_id = int(user_id or 0)
        except (TypeError, ValueError):
            safe_user_id = 0

        lock = template_lock or await self._get_warranty_email_template_lock(db_session, normalized_email)
        if not lock:
            return {"success": False, "error": "质保查询锁定记录不存在，请重新查询"}

        if lock.generated_redeem_code:
            return {
                "success": True,
                "code": lock.generated_redeem_code,
                "remaining_days": lock.generated_redeem_code_remaining_days,
                "entry_id": lock.generated_redeem_code_entry_id,
                "reused": True,
            }

        entry = warranty_entry
        if entry is None:
            entries = await self.get_warranty_email_entries_for_email(db_session, normalized_email)
            entry = entries[0] if entries else None
        if entry is None:
            return {"success": False, "error": "该邮箱未命中质保邮箱列表，无法生成兑换码"}

        remaining_days = self._get_warranty_entry_remaining_days(entry)
        if remaining_days is None or remaining_days <= 0:
            return {"success": False, "error": "该质保邮箱剩余时间不足，无法生成兑换码"}

        config = sub2api_config or await settings_service.get_sub2api_warranty_redeem_config(db_session)
        if not config.get("configured"):
            return {"success": False, "error": "Sub2API 质保兑换码配置未完成"}

        generated_code = sub2api_warranty_redeem_client.build_code(
            normalized_email,
            entry.id,
            config.get("code_prefix") or settings_service.DEFAULT_SUB2API_WARRANTY_CODE_PREFIX,
        )
        create_kwargs = {
            "base_url": config.get("base_url") or "",
            "admin_api_key": config.get("admin_api_key") or "",
            "code": generated_code,
            "group_id": int(config.get("subscription_group_id") or 0),
            "validity_days": remaining_days,
            "email": normalized_email,
            "entry_id": entry.id,
        }
        create_result = await sub2api_warranty_redeem_client.create_subscription_code(
            sub2api_user_id=safe_user_id if safe_user_id > 0 else None,
            **create_kwargs,
        )
        if not create_result.get("success"):
            return create_result

        lock.generated_redeem_code = create_result.get("code") or generated_code
        lock.generated_redeem_code_remaining_days = remaining_days
        lock.generated_redeem_code_entry_id = entry.id
        lock.generated_redeem_code_generated_at = create_result.get("generated_at") or get_now()
        lock.updated_at = get_now()
        try:
            await db_session.commit()
            await db_session.refresh(lock)
        except Exception as exc:
            await db_session.rollback()
            logger.error("保存质保名单判定生成兑换码失败 email=%s error=%s", normalized_email, exc)
            return {"success": False, "error": "兑换码已生成但本地保存失败，请稍后重试"}

        return {
            "success": True,
            "code": lock.generated_redeem_code,
            "remaining_days": remaining_days,
            "entry_id": entry.id,
            "reused": False,
        }

    async def force_generate_warranty_email_transfer_code(
        self,
        db_session: AsyncSession,
        *,
        entry_id: int,
    ) -> Dict[str, Any]:
        """后台按质保邮箱记录强制生成中转兑换码；已有则复用。"""
        entry = await self.get_warranty_email_entry_by_id(db_session, entry_id)
        if not entry:
            return {"success": False, "error": "质保邮箱记录不存在"}

        normalized_email = self.normalize_email(entry.email)
        if not normalized_email:
            return {"success": False, "error": "质保邮箱无效"}

        lock = await self._get_warranty_email_template_lock(db_session, normalized_email)
        if lock and lock.generated_redeem_code:
            return {
                "success": True,
                "code": lock.generated_redeem_code,
                "remaining_days": lock.generated_redeem_code_remaining_days,
                "entry_id": lock.generated_redeem_code_entry_id or entry.id,
                "reused": True,
                "entry": self.serialize_warranty_email_entry(entry, generated_code=lock),
            }

        if not lock:
            now = get_now()
            lock = WarrantyEmailTemplateLock(
                email=normalized_email,
                matched=True,
                template_key="match-default",
                created_at=now,
                updated_at=now,
            )
            db_session.add(lock)
            try:
                await db_session.commit()
                await db_session.refresh(lock)
            except IntegrityError:
                await db_session.rollback()
                lock = await self._get_warranty_email_template_lock(db_session, normalized_email)

        if not lock:
            return {"success": False, "error": "中转兑换码锁定记录创建失败，请稍后重试"}

        if not lock.matched:
            lock.matched = True
            lock.template_key = "match-default"
            lock.updated_at = get_now()
            await db_session.commit()
            await db_session.refresh(lock)

        result = await self.ensure_warranty_email_check_redeem_code(
            db_session=db_session,
            email=normalized_email,
            template_lock=lock,
            warranty_entry=entry,
        )
        if not result.get("success"):
            return result

        await db_session.refresh(entry)
        await db_session.refresh(lock)
        return {
            **result,
            "entry": self.serialize_warranty_email_entry(entry, generated_code=lock),
        }

    async def _get_or_create_warranty_email_template_lock(
        self,
        db_session: AsyncSession,
        email: str,
        matched: bool,
        templates: List[Dict[str, Any]],
    ) -> Optional[WarrantyEmailTemplateLock]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return None

        existing_lock = await self._get_warranty_email_template_lock(
            db_session,
            normalized_email,
        )
        if existing_lock:
            if bool(existing_lock.matched) != bool(matched):
                existing_lock.matched = matched
                existing_lock.template_key = self._pick_warranty_email_check_template_key(
                    templates,
                    matched,
                )
                existing_lock.updated_at = get_now()
                await db_session.commit()
                await db_session.refresh(existing_lock)
            return existing_lock

        template_key = self._pick_warranty_email_check_template_key(templates, matched)
        now = get_now()
        template_lock = WarrantyEmailTemplateLock(
            email=normalized_email,
            matched=matched,
            template_key=template_key,
            created_at=now,
            updated_at=now,
        )
        db_session.add(template_lock)

        try:
            await db_session.commit()
            await db_session.refresh(template_lock)
            return template_lock
        except IntegrityError:
            await db_session.rollback()
            return await self._get_warranty_email_template_lock(
                db_session,
                normalized_email,
            )

    async def _get_warranty_email_template_lock(
        self,
        db_session: AsyncSession,
        email: str,
    ) -> Optional[WarrantyEmailTemplateLock]:
        result = await db_session.execute(
            select(WarrantyEmailTemplateLock).where(
                WarrantyEmailTemplateLock.email == self.normalize_email(email)
            )
        )
        return result.scalar_one_or_none()

    def _pick_warranty_email_check_template_key(
        self,
        templates: List[Dict[str, Any]],
        matched: bool,
    ) -> str:
        template_ids = [
            str(template.get("id") or "").strip()
            for template in templates or []
            if str(template.get("id") or "").strip()
        ]
        if not template_ids:
            return "match-default" if matched else "miss-default"

        return secrets.choice(template_ids)

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
        capacity_expr = func.coalesce(Team.current_members, 0) + func.coalesce(Team.reserved_members, 0)
        stmt = (
            select(Team)
            .where(
                Team.status == "active",
                or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None)),
                capacity_expr < Team.max_members,
                Team.import_status == IMPORT_STATUS_CLASSIFIED,
                Team.team_type == TEAM_TYPE_STANDARD,
            )
            .order_by(
                func.coalesce(Team.reserved_members, 0).asc(),
                func.coalesce(Team.current_members, 0).asc(),
                Team.id.asc(),
            )
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
                Team.status == "full"
            )
            .order_by(RedemptionRecord.redeemed_at.desc(), Team.created_at.asc())
        )
        result = await db_session.execute(stmt)
        return result.scalars().first()

    async def _find_existing_warranty_team_from_records(
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
                Team.status.in_(["active", "full"])
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
            refresh_result = await self.team_service.refresh_team_state(
                team.id,
                db_session,
                source=SOURCE_USER_WARRANTY,
            )
            await db_session.commit()
            if not refresh_result.get("success"):
                logger.warning(
                    "检查 Team 现有成员失败，跳过 team_id=%s error=%s",
                    team.id,
                    refresh_result.get("error")
                )
                continue

            all_members = refresh_result.get("member_emails", [])
            already_exists = any(
                (member_email or "").strip().lower() == normalized_email
                for member_email in all_members
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
            select(Team).where(Team.id == entry.last_warranty_team_id)
        )
        team = result.scalar_one_or_none()
        if not team or team.status not in {"active", "full"}:
            return None

        refresh_result = await self.team_service.refresh_team_state(
            team.id,
            db_session,
            source=SOURCE_USER_WARRANTY,
        )
        await db_session.commit()
        if not refresh_result.get("success"):
            return None

        normalized_email = self.normalize_email(entry.email)
        all_members = refresh_result.get("member_emails", [])
        already_exists = any(
            self.normalize_email(member_email) == normalized_email
            for member_email in all_members
        )
        return team if already_exists else None

    async def claim_warranty_invite(
        self,
        db_session: AsyncSession,
        email: str,
        code: Optional[str] = None,
        entry_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        submitted_at = get_now()
        normalized_email = self.normalize_email(email)
        normalized_code = (code or "").strip()
        before_team_info = None

        try:
            if normalized_email:
                if normalized_code:
                    latest_contexts = await self._load_warranty_order_contexts_for_email(
                        db_session,
                        normalized_email,
                        warranty_entry=await self.get_warranty_email_entry(db_session, normalized_email),
                        target_code=normalized_code,
                    )
                    latest_context = latest_contexts[0] if latest_contexts else None
                else:
                    latest_context = await self._load_latest_team_context_for_email(
                        db_session,
                        normalized_email
                    )
                if latest_context:
                    before_team_info = latest_context.get("team_info")

            validation_result = await self.validate_warranty_claim_input(
                db_session=db_session,
                email=email,
                require_latest_team_banned=True,
                code=normalized_code or None,
                entry_id=entry_id,
            )
            if not validation_result.get("success"):
                await self._record_warranty_claim_result(
                    db_session=db_session,
                    email=normalized_email or (email or "").strip(),
                    submitted_at=submitted_at,
                    claim_status="failed",
                    before_team_info=before_team_info or validation_result.get("latest_team_info"),
                    failure_reason=validation_result.get("error"),
                )
                return validation_result

            normalized_email = validation_result["normalized_email"]
            warranty_entry = validation_result["warranty_entry"]
            selected_code = (
                validation_result.get("warranty_code")
                or (warranty_entry.last_redeem_code if warranty_entry else None)
            )
            before_team_info = validation_result.get("latest_team_info") or before_team_info

            existing_team = await self._find_existing_warranty_team_from_entry(db_session, warranty_entry)

            if existing_team:
                if warranty_entry and warranty_entry.last_warranty_team_id != existing_team.id:
                    warranty_entry.last_warranty_team_id = existing_team.id
                    await db_session.commit()
                    await db_session.refresh(warranty_entry)
                order_info = (
                    await self.get_warranty_order_info(db_session, normalized_email, selected_code, warranty_entry)
                    if selected_code
                    else None
                )
                warranty_info = (
                    order_info.get("warranty_info")
                    if order_info
                    else self.serialize_warranty_email_entry(warranty_entry) if warranty_entry else {}
                )

                await self._record_warranty_claim_result(
                    db_session=db_session,
                    email=normalized_email,
                    submitted_at=submitted_at,
                    claim_status="success",
                    before_team_info=before_team_info,
                    after_team=existing_team,
                )
                return {
                    "success": True,
                    "message": "质保邀请已存在，请直接查收邮箱中的邀请邮件。",
                    "team_info": {
                        "id": existing_team.id,
                        "team_name": existing_team.team_name,
                        "email": existing_team.email,
                        "expires_at": existing_team.expires_at.isoformat() if existing_team.expires_at else None
                    },
                    "warranty_info": warranty_info
                }

            warranty_teams = await self._get_available_warranty_teams(db_session)
            if not warranty_teams:
                logger.warning("质保申请失败: 没有可用的 Team")
                await self._record_warranty_claim_result(
                    db_session=db_session,
                    email=normalized_email,
                    submitted_at=submitted_at,
                    claim_status="failed",
                    before_team_info=before_team_info,
                    failure_reason="当前没有可用的 Team，请稍后再试",
                )
                return {"success": False, "error": "当前没有可用的 Team，请稍后再试"}

            last_error = None
            for team in warranty_teams:
                add_result = await self.team_service.add_team_member(
                    team.id,
                    normalized_email,
                    db_session,
                    source=SOURCE_USER_WARRANTY,
                )
                if add_result.get("success"):
                    await self._record_warranty_claim_success(
                        db_session=db_session,
                        entry=warranty_entry,
                        email=normalized_email,
                        team=team,
                        redeem_code=selected_code,
                    )
                    order_info = (
                        await self.get_warranty_order_info(db_session, normalized_email, selected_code, warranty_entry)
                        if selected_code
                        else None
                    )
                    await self._record_warranty_claim_result(
                        db_session=db_session,
                        email=normalized_email,
                        submitted_at=submitted_at,
                        claim_status="success",
                        before_team_info=before_team_info,
                        after_team=team,
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
                        "warranty_info": (
                            order_info.get("warranty_info")
                            if order_info
                            else self.serialize_warranty_email_entry(warranty_entry) if warranty_entry else {}
                        )
                    }

                last_error = add_result.get("error")
                if self._should_try_next_warranty_team(add_result):
                    logger.warning(
                        "质保邀请失败，命中可重试错误，尝试下一个 Team: team_id=%s error=%s",
                        team.id,
                        last_error
                    )
                    continue

                logger.warning(
                    "质保邀请失败: team_id=%s error=%s",
                    team.id,
                    last_error
                )
                await self._record_warranty_claim_result(
                    db_session=db_session,
                    email=normalized_email,
                    submitted_at=submitted_at,
                    claim_status="failed",
                    before_team_info=before_team_info,
                    failure_reason=last_error or "当前 Team 邀请失败，请稍后再试",
                )
                return {"success": False, "error": last_error or "当前 Team 邀请失败，请稍后再试"}

            await self._record_warranty_claim_result(
                db_session=db_session,
                email=normalized_email,
                submitted_at=submitted_at,
                claim_status="failed",
                before_team_info=before_team_info,
                failure_reason=last_error or "当前 Team 邀请失败，请稍后再试",
            )
            return {"success": False, "error": last_error or "当前 Team 邀请失败，请稍后再试"}

        except Exception as e:
            logger.error(f"质保邀请申请失败: {e}")
            await self._record_warranty_claim_result(
                db_session=db_session,
                email=normalized_email or (email or "").strip(),
                submitted_at=submitted_at,
                claim_status="failed",
                before_team_info=before_team_info,
                failure_reason=f"质保申请失败: {str(e)}",
            )
            return {"success": False, "error": f"质保申请失败: {str(e)}"}

    async def validate_warranty_claim_input(
        self,
        db_session: AsyncSession,
        email: str,
        require_latest_team_banned: bool = False,
        code: Optional[str] = None,
        entry_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        校验前台质保申请的基础输入：
        1. 邮箱在质保列表中
        2. 质保次数大于 0
        3. 质保有效期仍然有效
        4. 提交质保时，质保订单对应邮箱最近加入的 Team 必须为封禁状态
        """
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}

        normalized_code = (code or "").strip()
        warranty_entry = await self.find_warranty_email_entry_for_order(
            db_session=db_session,
            email=normalized_email,
            entry_id=entry_id,
            code=normalized_code or None,
            require_claimable=not entry_id and not normalized_code,
        )
        if not warranty_entry and not entry_id and not normalized_code:
            warranty_entry = await self.find_warranty_email_entry_for_order(
                db_session=db_session,
                email=normalized_email,
                require_claimable=False,
            )
        if not warranty_entry:
            if not entry_id and not normalized_code:
                logger.warning("质保申请失败: 邮箱不在质保列表中 email=%s", normalized_email)
                return {"success": False, "error": "该邮箱不在质保邮箱列表中"}
            logger.warning(
                "质保申请失败: 未找到质保邮箱列表订单 email=%s entry_id=%s code=%s",
                normalized_email,
                entry_id,
                normalized_code,
            )
            return {"success": False, "error": "未找到该邮箱绑定的质保订单"}

        entry_error = self._get_warranty_entry_claim_error(warranty_entry)
        if entry_error:
            logger.warning(
                "质保申请失败: 质保邮箱列表校验不通过 email=%s entry_id=%s code=%s error=%s",
                normalized_email,
                warranty_entry.id,
                normalized_code,
                entry_error,
            )
            return {"success": False, "error": entry_error}

        latest_record = None
        latest_team = None
        latest_team_info = None
        if require_latest_team_banned:
            selected_code = normalized_code or (warranty_entry.last_redeem_code or "").strip()
            latest_context = None
            try:
                latest_context = await self._load_latest_team_context_from_warranty_entry(
                    db_session,
                    warranty_entry,
                )
                if not latest_context and selected_code:
                    order_contexts = await self._load_warranty_order_contexts_for_email(
                        db_session,
                        normalized_email,
                        warranty_entry=warranty_entry,
                        target_code=selected_code,
                    )
                    latest_context = order_contexts[0] if order_contexts else None
                if not latest_context:
                    email_entries = await self.get_warranty_email_entries_for_email(
                        db_session,
                        normalized_email,
                    )
                    if len(email_entries) <= 1:
                        latest_context = await self._load_latest_team_context_for_email(
                            db_session,
                            normalized_email,
                            warranty_entry=warranty_entry
                        )
            except Exception as exc:
                logger.warning(
                    "质保申请读取参考 Team 信息失败 email=%s entry_id=%s error=%s",
                    normalized_email,
                    warranty_entry.id,
                    exc,
                )
                latest_context = None
            if latest_context:
                latest_record = latest_context.get("record")
                latest_team = latest_context.get("team")
                latest_team_info = latest_context.get("team_info")
            if not self._is_latest_team_banned(latest_team_info):
                error_message = self._build_latest_team_not_banned_message(latest_team_info)
                logger.warning(
                    "质保申请失败: 最近 Team 非封禁 email=%s entry_id=%s code=%s error=%s",
                    normalized_email,
                    warranty_entry.id,
                    selected_code,
                    error_message,
                )
                return {
                    "success": False,
                    "error": error_message,
                    "normalized_email": normalized_email,
                    "warranty_entry": warranty_entry,
                    "warranty_entry_id": warranty_entry.id,
                    "warranty_code": selected_code,
                    "latest_record": latest_record,
                    "latest_team": latest_team,
                    "latest_team_info": latest_team_info,
                }

        warranty_order = self._serialize_warranty_entry_order(
            warranty_entry,
            code=normalized_code or None,
            latest_team_info=latest_team_info,
        )

        return {
            "success": True,
            "normalized_email": normalized_email,
            "warranty_entry": warranty_entry,
            "warranty_entry_id": warranty_entry.id,
            "warranty_code": normalized_code or (warranty_entry.last_redeem_code or ""),
            "warranty_order": warranty_order,
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
                    sync_res = await self.team_service.refresh_team_state(
                        team.id,
                        db_session,
                        source=SOURCE_USER_WARRANTY,
                    )
                    await db_session.commit()
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
                        seconds = getattr(code_obj, "warranty_seconds", None)
                        if seconds is not None:
                            expiry_date = start_time + timedelta(seconds=max(int(seconds or 0), 0))
                        else:
                            days = code_obj.warranty_days if code_obj.warranty_days is not None else 30
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
                        sync_res = await self.team_service.refresh_team_state(
                            team.id,
                            db_session,
                            source=SOURCE_USER_WARRANTY,
                        )
                        await db_session.commit()
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
