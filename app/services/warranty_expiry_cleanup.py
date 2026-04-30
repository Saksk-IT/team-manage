"""质保到期自动清理服务。"""
import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import AsyncSessionLocal
from app.models import EmailWhitelistEntry, Team, TeamMemberSnapshot, WarrantyEmailEntry
from app.services.email_whitelist import email_whitelist_service
from app.services.settings import settings_service
from app.services.team import team_service
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)

WARRANTY_EXPIRY_CLEANUP_BATCH_SIZE = 20
WARRANTY_EXPIRY_CLEANUP_INTERVAL_MINUTES = 5
WARRANTY_EXPIRY_CLEANUP_IDLE_INTERVAL_MINUTES = 60


class WarrantyExpiryCleanupService:
    """检测已过期质保订单，并自动踢出对应邮箱、移出白名单。"""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._wake_event: Optional[asyncio.Event] = None
        self._run_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="warranty-expiry-cleanup",
        )
        logger.info("质保到期自动清理服务已启动")

    def wake(self) -> None:
        wake_event = self._wake_event
        if wake_event:
            wake_event.set()

    async def stop(self) -> None:
        task = self._task
        stop_event = self._stop_event

        self._task = None
        self._stop_event = None
        self._wake_event = None

        if stop_event:
            stop_event.set()

        if not task:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        logger.info("质保到期自动清理服务已停止")

    async def _wait_until_next_cycle(self, interval_minutes: int) -> bool:
        stop_event = self._stop_event
        if not stop_event:
            return False

        wait_tasks = {asyncio.create_task(stop_event.wait())}
        wake_event = self._wake_event
        if wake_event:
            wait_tasks.add(asyncio.create_task(wake_event.wait()))

        try:
            await asyncio.wait(
                wait_tasks,
                timeout=max(int(interval_minutes or 1), 1) * 60,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in wait_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*wait_tasks, return_exceptions=True)

        if stop_event.is_set():
            return False

        if wake_event and wake_event.is_set():
            wake_event.clear()
            logger.info("质保到期自动清理循环已被唤醒，将重新读取配置")

        return True

    async def _run_loop(self) -> None:
        while True:
            delay_minutes = WARRANTY_EXPIRY_CLEANUP_INTERVAL_MINUTES
            try:
                result = await self.run_once()
                delay_minutes = int(result.get("next_delay_minutes") or delay_minutes)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("质保到期自动清理循环执行失败: %s", exc)

            should_continue = await self._wait_until_next_cycle(delay_minutes)
            if not should_continue:
                return

    async def _is_enabled(self) -> bool:
        async with AsyncSessionLocal() as session:
            config = await settings_service.get_warranty_expiry_auto_cleanup_config(session)
            return bool(config.get("enabled"))

    async def _get_expired_entries(self, db_session: AsyncSession, *, limit: int) -> List[WarrantyEmailEntry]:
        now = get_now()
        active_entry = aliased(WarrantyEmailEntry)
        active_whitelist_exists = (
            select(EmailWhitelistEntry.id)
            .where(
                EmailWhitelistEntry.email == WarrantyEmailEntry.email,
                EmailWhitelistEntry.is_active.is_(True),
            )
            .exists()
        )
        active_warranty_entry_exists = (
            select(active_entry.id)
            .where(
                active_entry.id != WarrantyEmailEntry.id,
                active_entry.email == WarrantyEmailEntry.email,
                active_entry.remaining_claims > 0,
                active_entry.expires_at.is_not(None),
                active_entry.expires_at > now,
            )
            .exists()
        )
        snapshot_exists = (
            select(TeamMemberSnapshot.id)
            .where(
                TeamMemberSnapshot.team_id == WarrantyEmailEntry.last_warranty_team_id,
                TeamMemberSnapshot.email == WarrantyEmailEntry.email,
            )
            .exists()
        )
        stmt = (
            select(WarrantyEmailEntry)
            .where(
                WarrantyEmailEntry.expires_at.is_not(None),
                WarrantyEmailEntry.expires_at <= now,
                WarrantyEmailEntry.last_warranty_team_id.is_not(None),
                or_(
                    WarrantyEmailEntry.remaining_claims > 0,
                    snapshot_exists,
                    active_whitelist_exists & ~active_warranty_entry_exists,
                ),
            )
            .order_by(WarrantyEmailEntry.expires_at.asc(), WarrantyEmailEntry.id.asc())
            .limit(max(int(limit or 1), 1))
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def _has_active_warranty_entry_for_team(
        self,
        db_session: AsyncSession,
        *,
        email: str,
        team_id: int,
        exclude_entry_id: int,
    ) -> bool:
        normalized_email = email_whitelist_service.normalize_email(email)
        if not normalized_email or not team_id:
            return False

        now = get_now()
        result = await db_session.execute(
            select(WarrantyEmailEntry.id)
            .where(
                WarrantyEmailEntry.id != int(exclude_entry_id),
                WarrantyEmailEntry.email == normalized_email,
                WarrantyEmailEntry.last_warranty_team_id == int(team_id),
                WarrantyEmailEntry.remaining_claims > 0,
                WarrantyEmailEntry.expires_at.is_not(None),
                WarrantyEmailEntry.expires_at > now,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _has_active_warranty_entry(
        self,
        db_session: AsyncSession,
        *,
        email: str,
        exclude_entry_id: int,
    ) -> bool:
        normalized_email = email_whitelist_service.normalize_email(email)
        if not normalized_email:
            return False

        now = get_now()
        result = await db_session.execute(
            select(WarrantyEmailEntry.id)
            .where(
                WarrantyEmailEntry.id != int(exclude_entry_id),
                WarrantyEmailEntry.email == normalized_email,
                WarrantyEmailEntry.remaining_claims > 0,
                WarrantyEmailEntry.expires_at.is_not(None),
                WarrantyEmailEntry.expires_at > now,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _deactivate_whitelist_if_safe(
        self,
        db_session: AsyncSession,
        *,
        entry: WarrantyEmailEntry,
    ) -> bool:
        if await self._has_active_warranty_entry(
            db_session,
            email=entry.email,
            exclude_entry_id=entry.id,
        ):
            return False

        return await email_whitelist_service.deactivate_email(
            db_session,
            entry.email,
            note="质保订单到期，系统自动移出白名单",
            source=email_whitelist_service.SOURCE_EXPIRED_WARRANTY_CLEANUP,
            commit=False,
        )

    async def _mark_entry_processed(
        self,
        db_session: AsyncSession,
        entry: WarrantyEmailEntry,
        *,
        remove_snapshot: bool = True,
    ) -> None:
        entry.remaining_claims = 0
        entry.updated_at = get_now()
        normalized_email = email_whitelist_service.normalize_email(entry.email)
        if remove_snapshot and normalized_email and entry.last_warranty_team_id:
            await db_session.execute(
                delete(TeamMemberSnapshot).where(
                    TeamMemberSnapshot.team_id == entry.last_warranty_team_id,
                    TeamMemberSnapshot.email == normalized_email,
                )
            )
        await db_session.flush()

    @staticmethod
    def _serialize_entry(entry: WarrantyEmailEntry) -> Dict[str, Any]:
        return {
            "entry_id": entry.id,
            "email": entry.email,
            "team_id": entry.last_warranty_team_id,
            "redeem_code": entry.last_redeem_code,
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        }

    async def _cleanup_entry(self, db_session: AsyncSession, entry: WarrantyEmailEntry) -> Dict[str, Any]:
        payload = self._serialize_entry(entry)
        team_id = int(entry.last_warranty_team_id or 0)
        normalized_email = email_whitelist_service.normalize_email(entry.email)

        team = await db_session.get(Team, team_id) if team_id else None
        if not team:
            whitelist_deactivated = await self._deactivate_whitelist_if_safe(db_session, entry=entry)
            await self._mark_entry_processed(db_session, entry)
            return {
                **payload,
                "success": True,
                "message": "Team 已不存在，已完成白名单清理",
                "whitelist_deactivated": whitelist_deactivated,
                "member_removed": False,
            }

        if await self._has_active_warranty_entry_for_team(
            db_session,
            email=normalized_email,
            team_id=team_id,
            exclude_entry_id=entry.id,
        ):
            await self._mark_entry_processed(db_session, entry, remove_snapshot=False)
            return {
                **payload,
                "success": True,
                "message": "同邮箱在该 Team 仍有有效质保订单，已跳过踢出并完成到期标记",
                "whitelist_deactivated": False,
                "member_removed": False,
            }

        remove_result = await team_service.remove_invite_or_member(
            team_id=team_id,
            email=normalized_email,
            db_session=db_session,
        )
        if not remove_result.get("success"):
            return {
                **payload,
                "success": False,
                "error": remove_result.get("error") or "踢出 Team 成员失败",
                "whitelist_deactivated": False,
                "member_removed": False,
            }

        whitelist_deactivated = await self._deactivate_whitelist_if_safe(db_session, entry=entry)
        await self._mark_entry_processed(db_session, entry)
        return {
            **payload,
            "success": True,
            "message": remove_result.get("message") or "已清理到期质保订单",
            "whitelist_deactivated": whitelist_deactivated,
            "member_removed": True,
        }

    async def run_once(self) -> Dict[str, Any]:
        """执行一轮质保到期自动清理。"""
        async with self._run_lock:
            enabled = await self._is_enabled()
            if not enabled:
                logger.debug("质保到期自动清理已关闭，跳过本轮")
                return {
                    "enabled": False,
                    "processed_count": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "next_delay_minutes": WARRANTY_EXPIRY_CLEANUP_IDLE_INTERVAL_MINUTES,
                    "items": [],
                }

            async with AsyncSessionLocal() as session:
                entries = await self._get_expired_entries(
                    session,
                    limit=WARRANTY_EXPIRY_CLEANUP_BATCH_SIZE,
                )
                if not entries:
                    return {
                        "enabled": True,
                        "processed_count": 0,
                        "success_count": 0,
                        "failed_count": 0,
                        "next_delay_minutes": WARRANTY_EXPIRY_CLEANUP_IDLE_INTERVAL_MINUTES,
                        "items": [],
                    }

                items: List[Dict[str, Any]] = []
                for entry in entries:
                    try:
                        item = await self._cleanup_entry(session, entry)
                        if item.get("success"):
                            await session.commit()
                        else:
                            await session.rollback()
                        items.append(item)
                    except Exception as exc:
                        await session.rollback()
                        logger.exception(
                            "质保到期订单自动清理失败: entry_id=%s email=%s error=%s",
                            getattr(entry, "id", None),
                            getattr(entry, "email", None),
                            exc,
                        )
                        items.append({
                            **self._serialize_entry(entry),
                            "success": False,
                            "error": str(exc),
                            "whitelist_deactivated": False,
                            "member_removed": False,
                        })

                success_count = sum(1 for item in items if item.get("success"))
                failed_count = len(items) - success_count
                logger.info(
                    "质保到期自动清理完成: processed=%s success=%s failed=%s",
                    len(items),
                    success_count,
                    failed_count,
                )
                return {
                    "enabled": True,
                    "processed_count": len(items),
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "next_delay_minutes": WARRANTY_EXPIRY_CLEANUP_INTERVAL_MINUTES,
                    "items": items,
                }


warranty_expiry_cleanup_service = WarrantyExpiryCleanupService()
