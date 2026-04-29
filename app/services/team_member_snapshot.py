"""
Team 成员快照查询服务。
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, TeamMemberSnapshot

logger = logging.getLogger(__name__)


class TeamMemberSnapshotService:
    """Team 成员快照查询服务。"""

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

    @staticmethod
    def normalize_search(search: Optional[str]) -> Optional[str]:
        normalized_search = (search or "").strip()
        return normalized_search or None

    def serialize_snapshot(
        self,
        snapshot: TeamMemberSnapshot,
        team: Team,
        *,
        team_count: int = 1,
    ) -> Dict[str, Any]:
        member_state = (snapshot.member_state or "").strip().lower() or "joined"
        team_status = (team.status or "").strip().lower()
        safe_team_count = int(team_count or 0)

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
            "member_team_count": safe_team_count,
        }

    def _build_team_count_subquery(self):
        normalized_email_expr = func.lower(func.trim(TeamMemberSnapshot.email))
        return (
            select(
                normalized_email_expr.label("normalized_email"),
                func.count(func.distinct(TeamMemberSnapshot.team_id)).label("team_count"),
            )
            .group_by(normalized_email_expr)
            .subquery()
        )

    async def list_snapshots(
        self,
        db_session: AsyncSession,
        *,
        search: Optional[str] = None,
        team_id: Optional[int] = None,
        member_state: Optional[str] = None,
        team_count_min: Optional[int] = None,
        team_count_max: Optional[int] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> Dict[str, Any]:
        normalized_search = self.normalize_search(search)
        normalized_state = self.normalize_member_state(member_state)
        safe_page = max(int(page or 1), 1)
        safe_per_page = min(max(int(per_page or 100), 1), 100)
        normalized_snapshot_email = func.lower(func.trim(TeamMemberSnapshot.email))
        team_count_subquery = self._build_team_count_subquery()

        stmt = (
            select(TeamMemberSnapshot, Team, team_count_subquery.c.team_count)
            .join(Team, TeamMemberSnapshot.team_id == Team.id)
            .join(
                team_count_subquery,
                team_count_subquery.c.normalized_email == normalized_snapshot_email,
            )
        )
        count_stmt = (
            select(func.count(TeamMemberSnapshot.id))
            .select_from(TeamMemberSnapshot)
            .join(Team, TeamMemberSnapshot.team_id == Team.id)
            .join(
                team_count_subquery,
                team_count_subquery.c.normalized_email == normalized_snapshot_email,
            )
        )

        filters = []
        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            search_filters = [
                TeamMemberSnapshot.email.ilike(search_pattern),
                Team.email.ilike(search_pattern),
                Team.account_id.ilike(search_pattern),
                Team.team_name.ilike(search_pattern),
            ]
            if normalized_search.isdigit():
                search_filters.append(TeamMemberSnapshot.team_id == int(normalized_search))
            filters.append(or_(*search_filters))
        if team_id is not None:
            filters.append(TeamMemberSnapshot.team_id == int(team_id))
        if normalized_state:
            filters.append(TeamMemberSnapshot.member_state == normalized_state)
        if team_count_min is not None:
            filters.append(team_count_subquery.c.team_count >= int(team_count_min))
        if team_count_max is not None:
            filters.append(team_count_subquery.c.team_count <= int(team_count_max))

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
                team_count_subquery.c.team_count.desc(),
                TeamMemberSnapshot.updated_at.desc(),
                TeamMemberSnapshot.id.desc(),
            )
            .offset((safe_page - 1) * safe_per_page)
            .limit(safe_per_page)
        )
        result = await db_session.execute(stmt)
        records = [
            self.serialize_snapshot(snapshot, team, team_count=team_count)
            for snapshot, team, team_count in result.all()
        ]

        stats_subquery = (
            select(
                TeamMemberSnapshot.id.label("snapshot_id"),
                normalized_snapshot_email.label("normalized_email"),
                TeamMemberSnapshot.team_id.label("team_id"),
                TeamMemberSnapshot.member_state.label("member_state"),
                team_count_subquery.c.team_count.label("team_count"),
            )
            .join(Team, TeamMemberSnapshot.team_id == Team.id)
            .join(
                team_count_subquery,
                team_count_subquery.c.normalized_email == normalized_snapshot_email,
            )
        )
        if filters:
            stats_subquery = stats_subquery.where(*filters)
        stats_subquery = stats_subquery.subquery()

        stats_result = await db_session.execute(
            select(
                func.count(stats_subquery.c.snapshot_id),
                func.count(func.distinct(stats_subquery.c.normalized_email)),
                func.count(func.distinct(stats_subquery.c.team_id)),
                func.coalesce(func.sum(case((stats_subquery.c.member_state == "joined", 1), else_=0)), 0),
                func.coalesce(func.sum(case((stats_subquery.c.member_state == "invited", 1), else_=0)), 0),
                func.count(
                    func.distinct(
                        case(
                            (stats_subquery.c.team_count >= 2, stats_subquery.c.normalized_email),
                            else_=None,
                        )
                    )
                ),
            )
        )
        (
            total_records,
            unique_members,
            unique_teams,
            joined_count,
            invited_count,
            multi_team_members,
        ) = stats_result.one()

        return {
            "records": records,
            "stats": {
                "total_records": total_records or 0,
                "unique_members": unique_members or 0,
                "unique_teams": unique_teams or 0,
                "joined_count": joined_count or 0,
                "invited_count": invited_count or 0,
                "multi_team_members": multi_team_members or 0,
            },
            "pagination": {
                "current_page": safe_page,
                "per_page": safe_per_page,
                "total": total,
                "total_pages": total_pages,
            },
        }


team_member_snapshot_service = TeamMemberSnapshotService()
