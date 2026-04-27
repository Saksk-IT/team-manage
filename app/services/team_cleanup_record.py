"""
Team 自动清理记录服务
"""
import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TeamCleanupRecord

logger = logging.getLogger(__name__)


class TeamCleanupRecordService:
    """Team 自动清理记录服务"""

    STATUS_LABELS = {
        "success": "清理成功",
        "partial_failed": "部分失败",
        "failed": "清理失败",
    }

    @staticmethod
    def _serialize_json(value: Any) -> str:
        return json.dumps(value or [], ensure_ascii=False)

    @staticmethod
    def _deserialize_json(value: Optional[str]) -> list[Any]:
        raw_value = (value or "").strip()
        if not raw_value:
            return []

        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return []

        return parsed if isinstance(parsed, list) else []

    def _resolve_cleanup_status(
        self,
        removed_member_count: int,
        revoked_invite_count: int,
        failed_count: int,
    ) -> str:
        if failed_count <= 0:
            return "success"
        if removed_member_count > 0 or revoked_invite_count > 0:
            return "partial_failed"
        return "failed"

    async def create_record(
        self,
        db_session: AsyncSession,
        *,
        team_id: int,
        team_email: str,
        team_name: Optional[str],
        team_account_id: Optional[str],
        cleanup_summary: Dict[str, Any],
    ) -> Optional[TeamCleanupRecord]:
        removed_member_count = int(cleanup_summary.get("removed_member_count") or 0)
        revoked_invite_count = int(cleanup_summary.get("revoked_invite_count") or 0)
        failed_count = int(cleanup_summary.get("failed_count") or 0)

        if removed_member_count <= 0 and revoked_invite_count <= 0 and failed_count <= 0:
            return None

        cleanup_record = TeamCleanupRecord(
            team_id=team_id,
            team_email=(team_email or "").strip(),
            team_name=(team_name or "").strip() or None,
            team_account_id=(team_account_id or "").strip() or None,
            cleanup_status=self._resolve_cleanup_status(
                removed_member_count=removed_member_count,
                revoked_invite_count=revoked_invite_count,
                failed_count=failed_count,
            ),
            removed_member_count=removed_member_count,
            revoked_invite_count=revoked_invite_count,
            failed_count=failed_count,
            removed_member_emails=self._serialize_json(cleanup_summary.get("removed_member_emails")),
            revoked_invite_emails=self._serialize_json(cleanup_summary.get("revoked_invite_emails")),
            failed_items=self._serialize_json(cleanup_summary.get("failed_items")),
        )

        db_session.add(cleanup_record)
        await db_session.flush()

        logger.info(
            "已写入 Team 自动清理记录: team_id=%s removed=%s revoked=%s failed=%s",
            team_id,
            removed_member_count,
            revoked_invite_count,
            failed_count,
        )

        return cleanup_record

    def serialize_cleanup_record(self, record: TeamCleanupRecord) -> Dict[str, Any]:
        cleanup_status = (record.cleanup_status or "").strip().lower() or "success"
        removed_member_emails = self._deserialize_json(record.removed_member_emails)
        revoked_invite_emails = self._deserialize_json(record.revoked_invite_emails)
        failed_items = self._deserialize_json(record.failed_items)

        return {
            "id": record.id,
            "team_id": record.team_id,
            "team_email": record.team_email,
            "team_name": record.team_name,
            "team_account_id": record.team_account_id,
            "cleanup_status": cleanup_status,
            "cleanup_status_label": self.STATUS_LABELS.get(cleanup_status, "未知"),
            "removed_member_count": int(record.removed_member_count or 0),
            "revoked_invite_count": int(record.revoked_invite_count or 0),
            "failed_count": int(record.failed_count or 0),
            "removed_member_emails": removed_member_emails,
            "revoked_invite_emails": revoked_invite_emails,
            "failed_items": failed_items,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    async def list_cleanup_records(
        self,
        db_session: AsyncSession,
        *,
        search: Optional[str] = None,
        cleanup_status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        normalized_search = (search or "").strip()
        normalized_status = (cleanup_status or "").strip().lower()
        safe_page = max(int(page or 1), 1)
        safe_per_page = max(int(per_page or 20), 1)

        stmt = select(TeamCleanupRecord)
        count_stmt = select(func.count(TeamCleanupRecord.id))

        filters = []

        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            filters.append(
                or_(
                    TeamCleanupRecord.team_email.ilike(search_pattern),
                    TeamCleanupRecord.team_name.ilike(search_pattern),
                    TeamCleanupRecord.team_account_id.ilike(search_pattern),
                    TeamCleanupRecord.removed_member_emails.ilike(search_pattern),
                    TeamCleanupRecord.revoked_invite_emails.ilike(search_pattern),
                    TeamCleanupRecord.failed_items.ilike(search_pattern),
                )
            )

        if normalized_status in self.STATUS_LABELS:
            filters.append(TeamCleanupRecord.cleanup_status == normalized_status)

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        total_result = await db_session.execute(count_stmt)
        total = total_result.scalar() or 0

        total_pages = max((total + safe_per_page - 1) // safe_per_page, 1) if total else 1
        if safe_page > total_pages:
            safe_page = total_pages

        offset = (safe_page - 1) * safe_per_page
        stmt = (
            stmt.order_by(TeamCleanupRecord.created_at.desc(), TeamCleanupRecord.id.desc())
            .offset(offset)
            .limit(safe_per_page)
        )

        result = await db_session.execute(stmt)
        records = [self.serialize_cleanup_record(record) for record in result.scalars().all()]

        return {
            "records": records,
            "pagination": {
                "current_page": safe_page,
                "per_page": safe_per_page,
                "total": total,
                "total_pages": total_pages,
            },
        }


team_cleanup_record_service = TeamCleanupRecordService()
