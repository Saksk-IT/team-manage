"""
质保 Team 白名单服务

白名单用于决定质保 Team 自动刷新/清理时哪些邮箱必须保留。
它会自动包含质保邮箱列表中的有效账号，同时支持管理员手动维护和手动拉人入列。
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WarrantyEmailEntry, WarrantyTeamWhitelistEntry
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class WarrantyTeamWhitelistService:
    """质保 Team 白名单服务"""

    SOURCE_WARRANTY_EMAIL = "warranty_email"
    SOURCE_MANUAL = "manual"
    SOURCE_MANUAL_PULL = "manual_pull"

    SOURCE_LABELS = {
        SOURCE_WARRANTY_EMAIL: "质保邮箱列表有效账号",
        SOURCE_MANUAL: "管理员手动维护",
        SOURCE_MANUAL_PULL: "管理员手动拉人",
    }

    STATUS_LABELS = {
        "active": "启用",
        "inactive": "停用",
    }

    def normalize_email(self, email: Optional[str]) -> str:
        return (email or "").strip().lower()

    def _is_effective_warranty_email_entry(self, entry: WarrantyEmailEntry) -> bool:
        if not entry:
            return False
        if int(entry.remaining_claims or 0) <= 0:
            return False
        if not entry.expires_at:
            return False
        return entry.expires_at > get_now()

    def serialize_entry(self, entry: WarrantyTeamWhitelistEntry) -> Dict[str, Any]:
        status = "active" if bool(entry.is_active) else "inactive"
        source = entry.source or self.SOURCE_MANUAL
        return {
            "id": entry.id,
            "email": entry.email,
            "source": source,
            "source_label": self.SOURCE_LABELS.get(source, "未知来源"),
            "is_active": bool(entry.is_active),
            "status": status,
            "status_label": self.STATUS_LABELS.get(status, "未知"),
            "note": entry.note,
            "last_warranty_team_id": entry.last_warranty_team_id,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        }

    async def sync_from_warranty_email_entries(
        self,
        db_session: AsyncSession,
        *,
        commit: bool = False,
    ) -> Dict[str, int]:
        """把质保邮箱列表中的有效账号同步到质保 Team 白名单。"""
        result = await db_session.execute(select(WarrantyEmailEntry))
        warranty_entries = result.scalars().all()
        active_warranty_entries = {
            self.normalize_email(entry.email): entry
            for entry in warranty_entries
            if self._is_effective_warranty_email_entry(entry)
        }
        active_warranty_entries.pop("", None)
        legacy_manual_pull_entries = {
            self.normalize_email(entry.email): entry
            for entry in warranty_entries
            if (entry.source or "").strip().lower() == "manual"
            and int(entry.remaining_claims or 0) <= 0
            and not entry.expires_at
            and entry.last_warranty_team_id
        }
        legacy_manual_pull_entries.pop("", None)

        whitelist_result = await db_session.execute(select(WarrantyTeamWhitelistEntry))
        whitelist_entries = whitelist_result.scalars().all()
        whitelist_by_email = {
            self.normalize_email(entry.email): entry
            for entry in whitelist_entries
        }

        created_count = 0
        reactivated_count = 0
        deactivated_count = 0

        for email, warranty_entry in active_warranty_entries.items():
            existing_entry = whitelist_by_email.get(email)
            if existing_entry:
                if not existing_entry.is_active:
                    reactivated_count += 1
                existing_entry.is_active = True
                if warranty_entry.last_warranty_team_id and not existing_entry.last_warranty_team_id:
                    existing_entry.last_warranty_team_id = warranty_entry.last_warranty_team_id
                if existing_entry.source == self.SOURCE_WARRANTY_EMAIL and not existing_entry.note:
                    existing_entry.note = "自动同步自质保邮箱列表"
                continue

            db_session.add(
                WarrantyTeamWhitelistEntry(
                    email=email,
                    source=self.SOURCE_WARRANTY_EMAIL,
                    is_active=True,
                    note="自动同步自质保邮箱列表",
                    last_warranty_team_id=warranty_entry.last_warranty_team_id,
                )
            )
            created_count += 1

        for email, warranty_entry in legacy_manual_pull_entries.items():
            existing_entry = whitelist_by_email.get(email)
            if existing_entry:
                if not existing_entry.is_active:
                    reactivated_count += 1
                existing_entry.is_active = True
                if existing_entry.source == self.SOURCE_WARRANTY_EMAIL:
                    existing_entry.source = self.SOURCE_MANUAL_PULL
                if warranty_entry.last_warranty_team_id and not existing_entry.last_warranty_team_id:
                    existing_entry.last_warranty_team_id = warranty_entry.last_warranty_team_id
                continue

            db_session.add(
                WarrantyTeamWhitelistEntry(
                    email=email,
                    source=self.SOURCE_MANUAL_PULL,
                    is_active=True,
                    note="从历史手动拉人记录补写",
                    last_warranty_team_id=warranty_entry.last_warranty_team_id,
                )
            )
            created_count += 1

        active_emails = set(active_warranty_entries.keys())
        for entry in whitelist_entries:
            if entry.source != self.SOURCE_WARRANTY_EMAIL:
                continue
            if self.normalize_email(entry.email) in active_emails:
                continue
            if entry.is_active:
                entry.is_active = False
                deactivated_count += 1

        if created_count or reactivated_count or deactivated_count:
            await db_session.flush()
            logger.info(
                "质保 Team 白名单已同步质保邮箱列表: created=%s reactivated=%s deactivated=%s",
                created_count,
                reactivated_count,
                deactivated_count,
            )
            if commit:
                await db_session.commit()

        return {
            "created_count": created_count,
            "reactivated_count": reactivated_count,
            "deactivated_count": deactivated_count,
        }

    async def get_allowed_emails(self, db_session: AsyncSession) -> set[str]:
        await self.sync_from_warranty_email_entries(db_session, commit=False)
        result = await db_session.execute(
            select(WarrantyTeamWhitelistEntry.email).where(
                WarrantyTeamWhitelistEntry.is_active.is_(True)
            )
        )
        return {
            email
            for raw_email in result.scalars().all()
            if (email := self.normalize_email(raw_email))
        }

    async def list_entries(
        self,
        db_session: AsyncSession,
        *,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
        source_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        await self.sync_from_warranty_email_entries(db_session, commit=True)

        normalized_search = (search or "").strip()
        normalized_status = (status_filter or "").strip().lower()
        normalized_source = (source_filter or "").strip().lower()

        stmt = select(WarrantyTeamWhitelistEntry)
        filters = []

        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            filters.append(
                or_(
                    WarrantyTeamWhitelistEntry.email.ilike(search_pattern),
                    WarrantyTeamWhitelistEntry.note.ilike(search_pattern),
                )
            )

        if normalized_status in self.STATUS_LABELS:
            filters.append(WarrantyTeamWhitelistEntry.is_active.is_(normalized_status == "active"))

        if normalized_source in self.SOURCE_LABELS:
            filters.append(WarrantyTeamWhitelistEntry.source == normalized_source)

        if filters:
            stmt = stmt.where(and_(*filters))

        stmt = stmt.order_by(
            WarrantyTeamWhitelistEntry.is_active.desc(),
            WarrantyTeamWhitelistEntry.updated_at.desc(),
            WarrantyTeamWhitelistEntry.created_at.desc(),
        )
        result = await db_session.execute(stmt)
        return [self.serialize_entry(entry) for entry in result.scalars().all()]

    async def save_entry(
        self,
        db_session: AsyncSession,
        *,
        email: str,
        is_active: bool = True,
        note: Optional[str] = None,
        entry_id: Optional[int] = None,
        source: str = SOURCE_MANUAL,
        last_warranty_team_id: Optional[int] = None,
    ) -> WarrantyTeamWhitelistEntry:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            raise ValueError("邮箱不能为空")

        normalized_source = (source or self.SOURCE_MANUAL).strip().lower()
        if normalized_source not in self.SOURCE_LABELS:
            normalized_source = self.SOURCE_MANUAL

        current_entry = None
        if entry_id is not None:
            result = await db_session.execute(
                select(WarrantyTeamWhitelistEntry).where(WarrantyTeamWhitelistEntry.id == entry_id)
            )
            current_entry = result.scalar_one_or_none()
            if not current_entry:
                raise ValueError("质保 Team 白名单记录不存在")

        existing_entry_result = await db_session.execute(
            select(WarrantyTeamWhitelistEntry).where(WarrantyTeamWhitelistEntry.email == normalized_email)
        )
        existing_entry = existing_entry_result.scalar_one_or_none()
        if existing_entry and current_entry and existing_entry.id != current_entry.id:
            raise ValueError("该邮箱已存在其他白名单记录")

        target_entry = current_entry or existing_entry
        normalized_note = (note or "").strip() or None
        if target_entry:
            target_entry.email = normalized_email
            target_entry.is_active = bool(is_active)
            target_entry.note = normalized_note
            if target_entry.source == self.SOURCE_WARRANTY_EMAIL and normalized_source == self.SOURCE_MANUAL:
                target_entry.source = self.SOURCE_MANUAL
            elif target_entry.source != self.SOURCE_WARRANTY_EMAIL:
                target_entry.source = normalized_source
            if last_warranty_team_id and not target_entry.last_warranty_team_id:
                target_entry.last_warranty_team_id = last_warranty_team_id
        else:
            target_entry = WarrantyTeamWhitelistEntry(
                email=normalized_email,
                source=normalized_source,
                is_active=bool(is_active),
                note=normalized_note,
                last_warranty_team_id=last_warranty_team_id,
            )
            db_session.add(target_entry)

        await db_session.commit()
        await db_session.refresh(target_entry)
        return target_entry

    async def ensure_manual_entry(
        self,
        db_session: AsyncSession,
        *,
        email: str,
        source: str = SOURCE_MANUAL_PULL,
        last_warranty_team_id: Optional[int] = None,
        commit: bool = False,
    ) -> Optional[WarrantyTeamWhitelistEntry]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return None

        normalized_source = (source or self.SOURCE_MANUAL_PULL).strip().lower()
        if normalized_source not in self.SOURCE_LABELS:
            normalized_source = self.SOURCE_MANUAL_PULL

        result = await db_session.execute(
            select(WarrantyTeamWhitelistEntry).where(WarrantyTeamWhitelistEntry.email == normalized_email)
        )
        existing_entry = result.scalar_one_or_none()
        if existing_entry:
            existing_entry.is_active = True
            if existing_entry.source == self.SOURCE_WARRANTY_EMAIL:
                existing_entry.source = normalized_source
            if last_warranty_team_id and not existing_entry.last_warranty_team_id:
                existing_entry.last_warranty_team_id = last_warranty_team_id
            await db_session.flush()
            if commit:
                await db_session.commit()
                await db_session.refresh(existing_entry)
            return existing_entry

        whitelist_entry = WarrantyTeamWhitelistEntry(
            email=normalized_email,
            source=normalized_source,
            is_active=True,
            last_warranty_team_id=last_warranty_team_id,
        )
        db_session.add(whitelist_entry)
        await db_session.flush()
        if commit:
            await db_session.commit()
            await db_session.refresh(whitelist_entry)
        return whitelist_entry

    async def delete_entry(self, db_session: AsyncSession, entry_id: int) -> bool:
        result = await db_session.execute(
            select(WarrantyTeamWhitelistEntry).where(WarrantyTeamWhitelistEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            return False

        await db_session.delete(entry)
        await db_session.commit()
        return True


warranty_team_whitelist_service = WarrantyTeamWhitelistService()
