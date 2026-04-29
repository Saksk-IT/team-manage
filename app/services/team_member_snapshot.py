"""
Team 成员快照只读查询服务。
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, TeamMemberSnapshot

logger = logging.getLogger(__name__)


class TeamMemberSnapshotService:
    """Team 成员快照只读查询服务。"""

    MEMBER_STATE_LABELS = {
        "joined": "已加入",
        "invited": "待加入",
    }
    TEAM_STATUS_LABELS = {
        "active": "可用",
        "full": "已满",
        "expired": "已过期",
        "error": "异常",
        "banned": "封禁/失效",
    }

    @staticmethod
    def normalize_email(email: Optional[str]) -> Optional[str]:
        normalized_email = (email or "").strip().lower()
        return normalized_email or None

    def normalize_member_state(self, member_state: Optional[str]) -> Optional[str]:
        normalized_state = (member_state or "").strip().lower()
        if not normalized_state:
            return None
        if normalized_state not in self.MEMBER_STATE_LABELS:
            raise ValueError("成员状态筛选无效")
        return normalized_state

    def serialize_snapshot(
        self,
        snapshot: TeamMemberSnapshot,
        team: Team,
    ) -> Dict[str, Any]:
        member_state = (snapshot.member_state or "").strip().lower() or "joined"
        team_status = (team.status or "").strip().lower()

        return {
            "id": snapshot.id,
            "team_id": snapshot.team_id,
            "member_email": snapshot.email,
            "member_state": member_state,
            "member_state_label": self.MEMBER_STATE_LABELS.get(member_state, member_state or "未知"),
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
            "team_name": team.team_name,
            "team_email": team.email,
            "team_account_id": team.account_id,
            "team_status": team_status,
            "team_status_label": self.TEAM_STATUS_LABELS.get(team_status, team_status or "未知"),
        }

    async def list_snapshots(
        self,
        db_session: AsyncSession,
        *,
        email: Optional[str] = None,
        team_id: Optional[int] = None,
        member_state: Optional[str] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> Dict[str, Any]:
        normalized_email = self.normalize_email(email)
        normalized_state = self.normalize_member_state(member_state)
        safe_page = max(int(page or 1), 1)
        safe_per_page = min(max(int(per_page or 100), 1), 100)

        stmt = select(TeamMemberSnapshot, Team).join(Team, TeamMemberSnapshot.team_id == Team.id)
        count_stmt = (
            select(func.count(TeamMemberSnapshot.id))
            .select_from(TeamMemberSnapshot)
            .join(Team, TeamMemberSnapshot.team_id == Team.id)
        )

        filters = []
        if normalized_email:
            filters.append(func.lower(func.trim(TeamMemberSnapshot.email)) == normalized_email)
        if team_id is not None:
            filters.append(TeamMemberSnapshot.team_id == int(team_id))
        if normalized_state:
            filters.append(TeamMemberSnapshot.member_state == normalized_state)

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        total_result = await db_session.execute(count_stmt)
        total = total_result.scalar() or 0
        total_pages = max((total + safe_per_page - 1) // safe_per_page, 1) if total else 1
        if safe_page > total_pages:
            safe_page = total_pages

        stmt = (
            stmt.order_by(
                TeamMemberSnapshot.updated_at.desc(),
                TeamMemberSnapshot.id.desc(),
            )
            .offset((safe_page - 1) * safe_per_page)
            .limit(safe_per_page)
        )
        result = await db_session.execute(stmt)
        records = [
            self.serialize_snapshot(snapshot, team)
            for snapshot, team in result.all()
        ]

        return {
            "records": records,
            "pagination": {
                "current_page": safe_page,
                "per_page": safe_per_page,
                "total": total,
                "total_pages": total_pages,
            },
        }


team_member_snapshot_service = TeamMemberSnapshotService()
