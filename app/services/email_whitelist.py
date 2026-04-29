"""
邮箱白名单服务

邮箱白名单是系统自动清理的全局数据依赖。
它会自动汇入控制台 Team 兑换绑定邮箱、质保邮箱列表有效账号，
并支持管理员手动维护/手动拉入的账号。
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailWhitelistEntry, RedemptionCode, RedemptionRecord, Setting, WarrantyEmailEntry
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class EmailWhitelistService:
    """邮箱白名单服务"""

    SOURCE_CONSOLE_TEAM = "console_team"
    SOURCE_WARRANTY_EMAIL = "warranty_email"
    SOURCE_MANUAL = "manual"
    SOURCE_MANUAL_PULL = "manual_pull"

    SYNC_MODE_SETTING_KEY = "email_whitelist_sync_mode"
    SYNC_MODE_ALL = "all"
    SYNC_MODE_WARRANTY_ONLY = "warranty_only"

    SYSTEM_SOURCES = {SOURCE_CONSOLE_TEAM, SOURCE_WARRANTY_EMAIL}

    SOURCE_LABELS = {
        SOURCE_CONSOLE_TEAM: "控制台 Team 兑换绑定邮箱",
        SOURCE_WARRANTY_EMAIL: "质保邮箱列表有效账号",
        SOURCE_MANUAL: "管理员手动维护",
        SOURCE_MANUAL_PULL: "管理员手动拉入",
    }

    STATUS_LABELS = {
        "active": "启用",
        "inactive": "停用",
    }

    def normalize_email(self, email: Optional[str]) -> str:
        return (email or "").strip().lower()

    async def get_sync_mode(self, db_session: AsyncSession) -> str:
        result = await db_session.execute(
            select(Setting.value).where(Setting.key == self.SYNC_MODE_SETTING_KEY)
        )
        normalized_mode = (result.scalar_one_or_none() or self.SYNC_MODE_ALL).strip().lower()
        if normalized_mode == self.SYNC_MODE_WARRANTY_ONLY:
            return self.SYNC_MODE_WARRANTY_ONLY
        return self.SYNC_MODE_ALL

    async def _set_sync_mode(self, db_session: AsyncSession, sync_mode: str) -> None:
        normalized_mode = (sync_mode or self.SYNC_MODE_ALL).strip().lower()
        if normalized_mode not in {self.SYNC_MODE_ALL, self.SYNC_MODE_WARRANTY_ONLY}:
            normalized_mode = self.SYNC_MODE_ALL

        result = await db_session.execute(
            select(Setting).where(Setting.key == self.SYNC_MODE_SETTING_KEY)
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = normalized_mode
        else:
            db_session.add(
                Setting(
                    key=self.SYNC_MODE_SETTING_KEY,
                    value=normalized_mode,
                    description="邮箱白名单自动同步模式",
                )
            )

    def _is_effective_warranty_email_entry(self, entry: WarrantyEmailEntry) -> bool:
        if not entry:
            return False
        if int(entry.remaining_claims or 0) <= 0:
            return False
        if not entry.expires_at:
            return False
        return entry.expires_at > get_now()

    def serialize_entry(self, entry: EmailWhitelistEntry) -> Dict[str, Any]:
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
            "last_team_id": entry.last_warranty_team_id,
            "last_warranty_team_id": entry.last_warranty_team_id,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        }

    async def _collect_console_team_entries(self, db_session: AsyncSession) -> Dict[str, Optional[int]]:
        """收集控制台 Team 兑换绑定邮箱。"""
        console_entries: Dict[str, Optional[int]] = {}

        code_result = await db_session.execute(
            select(RedemptionCode.used_by_email, RedemptionCode.used_team_id).where(
                RedemptionCode.bound_team_id.is_not(None),
                RedemptionCode.used_team_id == RedemptionCode.bound_team_id,
                RedemptionCode.used_by_email.is_not(None),
            )
        )
        for email, team_id in code_result.all():
            normalized_email = self.normalize_email(email)
            if normalized_email:
                console_entries[normalized_email] = team_id

        record_result = await db_session.execute(
            select(RedemptionRecord.email, RedemptionRecord.team_id).where(
                RedemptionRecord.team_id.is_not(None),
                RedemptionRecord.email.is_not(None),
            )
        )
        for email, team_id in record_result.all():
            normalized_email = self.normalize_email(email)
            if normalized_email:
                console_entries.setdefault(normalized_email, team_id)

        return console_entries

    async def _collect_warranty_email_entries(self, db_session: AsyncSession) -> Dict[str, WarrantyEmailEntry]:
        result = await db_session.execute(select(WarrantyEmailEntry))
        warranty_entries = result.scalars().all()
        active_warranty_entries = {
            self.normalize_email(entry.email): entry
            for entry in warranty_entries
            if self._is_effective_warranty_email_entry(entry)
        }
        active_warranty_entries.pop("", None)
        return active_warranty_entries

    async def _collect_legacy_manual_pull_entries(self, db_session: AsyncSession) -> Dict[str, WarrantyEmailEntry]:
        result = await db_session.execute(select(WarrantyEmailEntry))
        warranty_entries = result.scalars().all()
        legacy_manual_pull_entries = {
            self.normalize_email(entry.email): entry
            for entry in warranty_entries
            if (entry.source or "").strip().lower() == "manual"
            and int(entry.remaining_claims or 0) <= 0
            and not entry.expires_at
            and entry.last_warranty_team_id
        }
        legacy_manual_pull_entries.pop("", None)
        return legacy_manual_pull_entries

    async def sync_from_dependency_sources(
        self,
        db_session: AsyncSession,
        *,
        commit: bool = False,
    ) -> Dict[str, int]:
        """同步系统自动清理依赖的邮箱来源到邮箱白名单。"""
        sync_mode = await self.get_sync_mode(db_session)
        if sync_mode == self.SYNC_MODE_WARRANTY_ONLY:
            return await self.sync_only_from_warranty_email_entries(
                db_session,
                commit=commit,
                update_sync_mode=False,
            )

        console_entries = await self._collect_console_team_entries(db_session)
        active_warranty_entries = await self._collect_warranty_email_entries(db_session)
        legacy_manual_pull_entries = await self._collect_legacy_manual_pull_entries(db_session)

        system_email_sources: Dict[str, str] = {
            email: self.SOURCE_WARRANTY_EMAIL
            for email in active_warranty_entries.keys()
        }
        system_email_sources.update({
            email: self.SOURCE_CONSOLE_TEAM
            for email in console_entries.keys()
        })

        whitelist_result = await db_session.execute(select(EmailWhitelistEntry))
        whitelist_entries = whitelist_result.scalars().all()
        whitelist_by_email = {
            self.normalize_email(entry.email): entry
            for entry in whitelist_entries
        }

        created_count = 0
        reactivated_count = 0
        deactivated_count = 0
        source_updated_count = 0

        for email, source in system_email_sources.items():
            existing_entry = whitelist_by_email.get(email)
            team_id = console_entries.get(email)
            if team_id is None and email in active_warranty_entries:
                team_id = active_warranty_entries[email].last_warranty_team_id
            note = (
                "自动同步自控制台 Team 兑换绑定邮箱"
                if source == self.SOURCE_CONSOLE_TEAM
                else "自动同步自质保邮箱列表"
            )

            if existing_entry:
                was_inactive = not existing_entry.is_active
                if was_inactive:
                    reactivated_count += 1
                existing_entry.is_active = True
                if was_inactive or existing_entry.source in self.SYSTEM_SOURCES or not existing_entry.source:
                    if existing_entry.source != source:
                        source_updated_count += 1
                    existing_entry.source = source
                if team_id and not existing_entry.last_warranty_team_id:
                    existing_entry.last_warranty_team_id = team_id
                if not existing_entry.note and existing_entry.source == source:
                    existing_entry.note = note
                continue

            whitelist_entry = EmailWhitelistEntry(
                email=email,
                source=source,
                is_active=True,
                note=note,
                last_warranty_team_id=team_id,
            )
            db_session.add(whitelist_entry)
            whitelist_by_email[email] = whitelist_entry
            created_count += 1

        active_system_emails = set(system_email_sources.keys())
        for entry in whitelist_entries:
            normalized_email = self.normalize_email(entry.email)
            if entry.source not in self.SYSTEM_SOURCES:
                continue
            if normalized_email in active_system_emails:
                target_source = system_email_sources[normalized_email]
                if entry.source != target_source:
                    entry.source = target_source
                    source_updated_count += 1
                continue
            if entry.is_active:
                entry.is_active = False
                deactivated_count += 1

        for email, warranty_entry in legacy_manual_pull_entries.items():
            existing_entry = whitelist_by_email.get(email)
            if existing_entry:
                if not existing_entry.is_active and existing_entry.source not in self.SYSTEM_SOURCES:
                    continue
                if not existing_entry.is_active:
                    reactivated_count += 1
                existing_entry.is_active = True
                if existing_entry.source in self.SYSTEM_SOURCES:
                    existing_entry.source = self.SOURCE_MANUAL_PULL
                    source_updated_count += 1
                if warranty_entry.last_warranty_team_id and not existing_entry.last_warranty_team_id:
                    existing_entry.last_warranty_team_id = warranty_entry.last_warranty_team_id
                continue

            db_session.add(
                EmailWhitelistEntry(
                    email=email,
                    source=self.SOURCE_MANUAL_PULL,
                    is_active=True,
                    note="从历史手动拉入记录补写",
                    last_warranty_team_id=warranty_entry.last_warranty_team_id,
                )
            )
            created_count += 1

        if created_count or reactivated_count or deactivated_count or source_updated_count:
            await db_session.flush()
            logger.info(
                "邮箱白名单已同步自动清理依赖源: created=%s reactivated=%s deactivated=%s source_updated=%s",
                created_count,
                reactivated_count,
                deactivated_count,
                source_updated_count,
            )
            if commit:
                await db_session.commit()

        return {
            "created_count": created_count,
            "reactivated_count": reactivated_count,
            "deactivated_count": deactivated_count,
            "source_updated_count": source_updated_count,
        }

    async def sync_only_from_warranty_email_entries(
        self,
        db_session: AsyncSession,
        *,
        commit: bool = False,
        update_sync_mode: bool = True,
    ) -> Dict[str, int]:
        """一键同步邮箱白名单：仅保留当前有效的质保邮箱来源。"""
        active_warranty_entries = await self._collect_warranty_email_entries(db_session)

        whitelist_result = await db_session.execute(select(EmailWhitelistEntry))
        whitelist_entries = whitelist_result.scalars().all()
        whitelist_by_email = {
            self.normalize_email(entry.email): entry
            for entry in whitelist_entries
        }

        target_emails = set(active_warranty_entries.keys())
        created_count = 0
        reactivated_count = 0
        deactivated_count = 0
        source_updated_count = 0

        if update_sync_mode:
            await self._set_sync_mode(db_session, self.SYNC_MODE_WARRANTY_ONLY)

        for email, warranty_entry in active_warranty_entries.items():
            existing_entry = whitelist_by_email.get(email)
            if existing_entry:
                if not existing_entry.is_active:
                    reactivated_count += 1
                existing_entry.is_active = True
                if existing_entry.source != self.SOURCE_WARRANTY_EMAIL:
                    existing_entry.source = self.SOURCE_WARRANTY_EMAIL
                    source_updated_count += 1
                if warranty_entry.last_warranty_team_id and not existing_entry.last_warranty_team_id:
                    existing_entry.last_warranty_team_id = warranty_entry.last_warranty_team_id
                if not existing_entry.note:
                    existing_entry.note = "一键同步自质保邮箱列表"
                continue

            db_session.add(
                EmailWhitelistEntry(
                    email=email,
                    source=self.SOURCE_WARRANTY_EMAIL,
                    is_active=True,
                    note="一键同步自质保邮箱列表",
                    last_warranty_team_id=warranty_entry.last_warranty_team_id,
                )
            )
            created_count += 1

        for entry in whitelist_entries:
            normalized_email = self.normalize_email(entry.email)
            if normalized_email in target_emails:
                continue
            if entry.is_active:
                entry.is_active = False
                deactivated_count += 1
            if not entry.note:
                entry.note = "已由一键同步质保邮箱列表移出"

        has_changes = any([
            update_sync_mode,
            created_count,
            reactivated_count,
            deactivated_count,
            source_updated_count,
        ])
        if has_changes:
            await db_session.flush()
            logger.info(
                "邮箱白名单已一键同步质保邮箱列表: target=%s created=%s reactivated=%s deactivated=%s source_updated=%s",
                len(target_emails),
                created_count,
                reactivated_count,
                deactivated_count,
                source_updated_count,
            )
            if commit:
                await db_session.commit()

        return {
            "target_count": len(target_emails),
            "created_count": created_count,
            "reactivated_count": reactivated_count,
            "deactivated_count": deactivated_count,
            "source_updated_count": source_updated_count,
        }

    async def sync_from_warranty_email_entries(
        self,
        db_session: AsyncSession,
        *,
        commit: bool = False,
    ) -> Dict[str, int]:
        """兼容旧调用：同步邮箱白名单依赖源。"""
        return await self.sync_from_dependency_sources(db_session, commit=commit)

    async def get_allowed_emails(self, db_session: AsyncSession) -> set[str]:
        await self.sync_from_dependency_sources(db_session, commit=False)
        result = await db_session.execute(
            select(EmailWhitelistEntry.email).where(
                EmailWhitelistEntry.is_active.is_(True)
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
        await self.sync_from_dependency_sources(db_session, commit=True)

        normalized_search = (search or "").strip()
        normalized_status = (status_filter or "").strip().lower()
        normalized_source = (source_filter or "").strip().lower()

        stmt = select(EmailWhitelistEntry)
        filters = []

        if normalized_search:
            search_pattern = f"%{normalized_search}%"
            filters.append(
                or_(
                    EmailWhitelistEntry.email.ilike(search_pattern),
                    EmailWhitelistEntry.note.ilike(search_pattern),
                )
            )

        if normalized_status in self.STATUS_LABELS:
            filters.append(EmailWhitelistEntry.is_active.is_(normalized_status == "active"))

        if normalized_source in self.SOURCE_LABELS:
            filters.append(EmailWhitelistEntry.source == normalized_source)

        if filters:
            stmt = stmt.where(and_(*filters))

        stmt = stmt.order_by(
            EmailWhitelistEntry.is_active.desc(),
            EmailWhitelistEntry.updated_at.desc(),
            EmailWhitelistEntry.created_at.desc(),
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
    ) -> EmailWhitelistEntry:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            raise ValueError("邮箱不能为空")

        normalized_source = (source or self.SOURCE_MANUAL).strip().lower()
        if normalized_source not in self.SOURCE_LABELS:
            normalized_source = self.SOURCE_MANUAL

        current_entry = None
        if entry_id is not None:
            result = await db_session.execute(
                select(EmailWhitelistEntry).where(EmailWhitelistEntry.id == entry_id)
            )
            current_entry = result.scalar_one_or_none()
            if not current_entry:
                raise ValueError("邮箱白名单记录不存在")

        existing_entry_result = await db_session.execute(
            select(EmailWhitelistEntry).where(EmailWhitelistEntry.email == normalized_email)
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
            if target_entry.source not in self.SYSTEM_SOURCES:
                target_entry.source = normalized_source
            if last_warranty_team_id and not target_entry.last_warranty_team_id:
                target_entry.last_warranty_team_id = last_warranty_team_id
        else:
            target_entry = EmailWhitelistEntry(
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
        reactivate_existing: bool = True,
    ) -> Optional[EmailWhitelistEntry]:
        normalized_email = self.normalize_email(email)
        if not normalized_email:
            return None

        normalized_source = (source or self.SOURCE_MANUAL_PULL).strip().lower()
        if normalized_source not in self.SOURCE_LABELS:
            normalized_source = self.SOURCE_MANUAL_PULL

        result = await db_session.execute(
            select(EmailWhitelistEntry).where(EmailWhitelistEntry.email == normalized_email)
        )
        existing_entry = result.scalar_one_or_none()
        if existing_entry:
            if not existing_entry.is_active and not reactivate_existing:
                return existing_entry
            existing_entry.is_active = True
            if existing_entry.source in self.SYSTEM_SOURCES:
                existing_entry.source = normalized_source
            if last_warranty_team_id and not existing_entry.last_warranty_team_id:
                existing_entry.last_warranty_team_id = last_warranty_team_id
            await db_session.flush()
            if commit:
                await db_session.commit()
                await db_session.refresh(existing_entry)
            return existing_entry

        whitelist_entry = EmailWhitelistEntry(
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
            select(EmailWhitelistEntry).where(EmailWhitelistEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            return False

        entry.is_active = False
        if not entry.note:
            entry.note = "已由管理员移出白名单"
        await db_session.commit()
        return True


email_whitelist_service = EmailWhitelistService()
