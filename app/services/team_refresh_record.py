"""
Team 刷新记录服务
"""
import logging
from datetime import datetime, time
from typing import Any, Dict, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, TeamRefreshRecord

logger = logging.getLogger(__name__)


SOURCE_AUTO = "auto"
SOURCE_ADMIN_MANUAL = "admin_manual"
SOURCE_ADMIN_FORCE = "admin_force"
SOURCE_ADMIN_BATCH = "admin_batch"
SOURCE_ADMIN_MEMBER = "admin_member"
SOURCE_USER_REDEEM = "user_redeem"
SOURCE_USER_WARRANTY = "user_warranty"
SOURCE_SYSTEM = "system"
SOURCE_UNKNOWN = "unknown"


class TeamRefreshRecordService:
    """Team 刷新记录服务"""

    SOURCE_LABELS = {
        SOURCE_AUTO: "后台自动",
        SOURCE_ADMIN_MANUAL: "后台手动",
        SOURCE_ADMIN_FORCE: "后台强制刷新 AT",
        SOURCE_ADMIN_BATCH: "后台批量",
        SOURCE_ADMIN_MEMBER: "后台成员操作",
        SOURCE_USER_REDEEM: "前台兑换",
        SOURCE_USER_WARRANTY: "前台质保",
        SOURCE_SYSTEM: "系统同步",
        SOURCE_UNKNOWN: "未知来源",
    }
    REFRESH_STATUS_LABELS = {
        "success": "刷新成功",
        "failed": "刷新失败",
    }
    TEAM_STATUS_LABELS = {
        "active": "可用",
        "full": "已满",
        "expired": "已过期",
        "error": "异常",
        "banned": "封禁/失效",
    }

    def normalize_source(self, source: Optional[str]) -> str:
        normalized_source = (source or "").strip().lower()
        return normalized_source if normalized_source in self.SOURCE_LABELS else SOURCE_UNKNOWN

    def _normalize_status(self, status_value: Optional[str], allowed_values: set[str]) -> str:
        normalized_status = (status_value or "").strip().lower()
        return normalized_status if normalized_status in allowed_values else ""

    def _parse_date_boundary(self, value: Optional[str], *, is_end: bool = False) -> Optional[datetime]:
        raw_value = (value or "").strip()
        if not raw_value:
            return None

        try:
            if "T" in raw_value or " " in raw_value:
                return datetime.fromisoformat(raw_value)
            parsed_date = datetime.fromisoformat(raw_value).date()
            boundary_time = time.max if is_end else time.min
            return datetime.combine(parsed_date, boundary_time)
        except ValueError:
            return None

    async def create_record(
        self,
        db_session: AsyncSession,
        *,
        team: Team,
        source: Optional[str],
        force_refresh: bool,
        refresh_result: Dict[str, Any],
    ) -> TeamRefreshRecord:
        refresh_succeeded = bool(refresh_result.get("success"))
        refresh_record = TeamRefreshRecord(
            team_id=team.id,
            team_email=(team.email or "").strip(),
            team_name=(team.team_name or "").strip() or None,
            team_account_id=(team.account_id or "").strip() or None,
            source=self.normalize_source(source),
            refresh_status="success" if refresh_succeeded else "failed",
            force_refresh=bool(force_refresh),
            team_status=(team.status or "").strip() or None,
            current_members=team.current_members,
            max_members=team.max_members,
            message=(refresh_result.get("message") or "").strip() or None,
            error=(refresh_result.get("error") or "").strip() or None,
            error_code=(refresh_result.get("error_code") or "").strip() or None,
            cleanup_record_id=refresh_result.get("cleanup_record_id"),
            cleanup_removed_member_count=int(refresh_result.get("cleanup_removed_member_count") or 0),
            cleanup_revoked_invite_count=int(refresh_result.get("cleanup_revoked_invite_count") or 0),
            cleanup_failed_count=int(refresh_result.get("cleanup_failed_count") or 0),
        )

        db_session.add(refresh_record)
        await db_session.flush()

        logger.info(
            "已写入 Team 刷新记录: team_id=%s source=%s status=%s team_status=%s",
            team.id,
            refresh_record.source,
            refresh_record.refresh_status,
            refresh_record.team_status,
        )
        return refresh_record

    def serialize_refresh_record(self, record: TeamRefreshRecord) -> Dict[str, Any]:
        source = (record.source or SOURCE_UNKNOWN).strip().lower()
        refresh_status = (record.refresh_status or "failed").strip().lower()
        team_status = (record.team_status or "").strip().lower()
        cleanup_total = (
            int(record.cleanup_removed_member_count or 0)
            + int(record.cleanup_revoked_invite_count or 0)
            + int(record.cleanup_failed_count or 0)
        )

        return {
            "id": record.id,
            "team_id": record.team_id,
            "team_email": record.team_email,
            "team_name": record.team_name,
            "team_account_id": record.team_account_id,
            "source": source,
            "source_label": self.SOURCE_LABELS.get(source, "未知来源"),
            "refresh_status": refresh_status,
            "refresh_status_label": self.REFRESH_STATUS_LABELS.get(refresh_status, "未知结果"),
            "force_refresh": bool(record.force_refresh),
            "team_status": team_status,
            "team_status_label": self.TEAM_STATUS_LABELS.get(team_status, team_status or "未知"),
            "current_members": record.current_members,
            "max_members": record.max_members,
            "message": record.message,
            "error": record.error,
            "error_code": record.error_code,
            "cleanup_record_id": record.cleanup_record_id,
            "cleanup_removed_member_count": int(record.cleanup_removed_member_count or 0),
            "cleanup_revoked_invite_count": int(record.cleanup_revoked_invite_count or 0),
            "cleanup_failed_count": int(record.cleanup_failed_count or 0),
            "cleanup_total": cleanup_total,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    async def list_refresh_records(
        self,
        db_session: AsyncSession,
        *,
        search: Optional[str] = None,
        source: Optional[str] = None,
        refresh_status: Optional[str] = None,
        team_status: Optional[str] = None,
        has_cleanup: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        normalized_search = (search or "").strip()
        normalized_source = self.normalize_source(source) if (source or "").strip() else ""
        normalized_refresh_status = self._normalize_status(
            refresh_status,
            set(self.REFRESH_STATUS_LABELS),
        )
        normalized_team_status = self._normalize_status(
            team_status,
            set(self.TEAM_STATUS_LABELS),
        )
        normalized_has_cleanup = (has_cleanup or "").strip().lower()
        start_datetime = self._parse_date_boundary(start_date)
        end_datetime = self._parse_date_boundary(end_date, is_end=True)
        safe_page = max(int(page or 1), 1)
        safe_per_page = min(max(int(per_page or 20), 1), 100)

        stmt = select(TeamRefreshRecord)
        count_stmt = select(func.count(TeamRefreshRecord.id))
        filters = []

        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            search_filters = [
                TeamRefreshRecord.team_email.ilike(search_pattern),
                TeamRefreshRecord.team_name.ilike(search_pattern),
                TeamRefreshRecord.team_account_id.ilike(search_pattern),
                TeamRefreshRecord.message.ilike(search_pattern),
                TeamRefreshRecord.error.ilike(search_pattern),
                TeamRefreshRecord.error_code.ilike(search_pattern),
            ]
            if normalized_search.isdigit():
                search_filters.append(TeamRefreshRecord.team_id == int(normalized_search))
            filters.append(or_(*search_filters))

        if normalized_source:
            filters.append(TeamRefreshRecord.source == normalized_source)

        if normalized_refresh_status:
            filters.append(TeamRefreshRecord.refresh_status == normalized_refresh_status)

        if normalized_team_status:
            filters.append(TeamRefreshRecord.team_status == normalized_team_status)

        cleanup_total = (
            func.coalesce(TeamRefreshRecord.cleanup_removed_member_count, 0)
            + func.coalesce(TeamRefreshRecord.cleanup_revoked_invite_count, 0)
            + func.coalesce(TeamRefreshRecord.cleanup_failed_count, 0)
        )
        if normalized_has_cleanup == "with_cleanup":
            filters.append(or_(TeamRefreshRecord.cleanup_record_id.is_not(None), cleanup_total > 0))
        elif normalized_has_cleanup == "without_cleanup":
            filters.append(and_(TeamRefreshRecord.cleanup_record_id.is_(None), cleanup_total == 0))

        if start_datetime:
            filters.append(TeamRefreshRecord.created_at >= start_datetime)
        if end_datetime:
            filters.append(TeamRefreshRecord.created_at <= end_datetime)

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        total_result = await db_session.execute(count_stmt)
        total = total_result.scalar() or 0
        total_pages = max((total + safe_per_page - 1) // safe_per_page, 1) if total else 1
        if safe_page > total_pages:
            safe_page = total_pages

        stmt = (
            stmt.order_by(TeamRefreshRecord.created_at.desc(), TeamRefreshRecord.id.desc())
            .offset((safe_page - 1) * safe_per_page)
            .limit(safe_per_page)
        )
        result = await db_session.execute(stmt)
        records = [self.serialize_refresh_record(record) for record in result.scalars().all()]

        return {
            "records": records,
            "pagination": {
                "current_page": safe_page,
                "per_page": safe_per_page,
                "total": total,
                "total_pages": total_pages,
            },
        }


team_refresh_record_service = TeamRefreshRecordService()
