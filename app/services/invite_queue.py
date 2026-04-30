"""
前台拉人队列服务

将兑换/质保请求先写入数据库并预占 Team 席位，再由后台 worker 串行处理单个 Team 的拉人请求，
避免高并发下多个请求同时命中同一个 Team 导致超额邀请。
"""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import InviteJob, RedemptionCode, RedemptionRecord, Team, TeamMemberSnapshot, WarrantyEmailEntry
from app.services.email_whitelist import email_whitelist_service
from app.services.redemption import RedemptionService
from app.services.team import IMPORT_STATUS_CLASSIFIED, TEAM_TYPE_NUMBER_POOL, TEAM_TYPE_STANDARD, TeamService
from app.services.team_refresh_record import SOURCE_USER_REDEEM, SOURCE_USER_WARRANTY
from app.services.warranty import warranty_service
from app.services.settings import settings_service
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)

JOB_TYPE_REDEEM = "redeem"
JOB_TYPE_WARRANTY = "warranty"
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_SUCCESS = "success"
JOB_STATUS_FAILED = "failed"
ACTIVE_JOB_STATUSES = (JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING)
TERMINAL_JOB_STATUSES = (JOB_STATUS_SUCCESS, JOB_STATUS_FAILED)
DEFAULT_POLL_AFTER_MS = 1500
DEFAULT_ACTIVE_TEAM_LIMIT = 10


class InviteQueueService:
    """数据库预占 + 后台 worker 的前台拉人队列。"""

    def __init__(self) -> None:
        self.redemption_service = RedemptionService()
        self.team_service = TeamService()
        self.warranty_service = warranty_service
        self._submit_lock = asyncio.Lock()
        self._team_locks = defaultdict(asyncio.Lock)
        self._stop_event: Optional[asyncio.Event] = None
        self._tasks: List[asyncio.Task] = []

    def _get_active_team_limit(self) -> int:
        try:
            return max(int(settings.invite_queue_active_team_limit or DEFAULT_ACTIVE_TEAM_LIMIT), 1)
        except (TypeError, ValueError):
            return DEFAULT_ACTIVE_TEAM_LIMIT

    def _get_default_max_attempts(self) -> int:
        return self._get_active_team_limit()

    async def start(self) -> None:
        if self._tasks:
            return

        worker_count = max(int(settings.invite_queue_worker_count or 3), 1)
        self._stop_event = asyncio.Event()
        await self.recover_stale_processing_jobs()
        self._tasks = [
            asyncio.create_task(self._worker_loop(index + 1), name=f"invite-queue-worker-{index + 1}")
            for index in range(worker_count)
        ]
        logger.info("前台拉人队列已启动: worker_count=%s", worker_count)

    async def stop(self) -> None:
        if not self._tasks:
            return

        if self._stop_event:
            self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._stop_event = None
        logger.info("前台拉人队列已停止")

    def serialize_job(self, job: InviteJob) -> Dict[str, Any]:
        payload = self._decode_payload(job.result_payload)
        response: Dict[str, Any] = {
            "success": job.status != JOB_STATUS_FAILED,
            "queued": job.status in ACTIVE_JOB_STATUSES,
            "job_id": job.id,
            "job_type": job.job_type,
            "job_status": job.status,
            "status": job.status,
            "attempt_count": int(job.attempt_count or 0),
            "poll_after_ms": DEFAULT_POLL_AFTER_MS,
            "message": self._get_job_message(job),
            "error": job.error,
            "result": payload,
        }
        if job.status == JOB_STATUS_SUCCESS and isinstance(payload, dict):
            response.update(payload)
            response["success"] = True
            response["queued"] = False
            response["job_status"] = JOB_STATUS_SUCCESS
            response["status"] = JOB_STATUS_SUCCESS
        elif job.status == JOB_STATUS_FAILED:
            response["success"] = False
            response["queued"] = False
        return response

    async def get_job(self, db_session: AsyncSession, job_id: int) -> Optional[InviteJob]:
        result = await db_session.execute(select(InviteJob).where(InviteJob.id == job_id))
        return result.scalar_one_or_none()

    async def _get_redeem_team_type(self, db_session: AsyncSession) -> str:
        config = await settings_service.get_number_pool_config(db_session)
        return TEAM_TYPE_NUMBER_POOL if config.get("enabled") else TEAM_TYPE_STANDARD

    @staticmethod
    def _get_team_pool_label(team_type: Optional[str]) -> str:
        return "号池 Team" if team_type == TEAM_TYPE_NUMBER_POOL else "控制台 Team"

    async def submit_redeem_job(
        self,
        db_session: AsyncSession,
        email: str,
        code: str,
    ) -> Dict[str, Any]:
        normalized_email = self._normalize_email(email)
        normalized_code = (code or "").strip()
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}
        if not normalized_code:
            return {"success": False, "error": "兑换码不能为空"}

        async with self._submit_lock:
            try:
                existing_job = await self._find_active_redeem_job(db_session, normalized_code)
                if existing_job:
                    if self._normalize_email(existing_job.email) != normalized_email:
                        return {
                            "success": False,
                            "error": "该兑换码正在被其他邮箱处理，请勿重复使用",
                        }
                    return self.serialize_job(existing_job)

                validate_result = await self.redemption_service.validate_code(normalized_code, db_session)
                if not validate_result.get("success"):
                    await db_session.rollback()
                    return {"success": False, "error": validate_result.get("error") or "兑换码校验失败"}
                if not validate_result.get("valid"):
                    if validate_result.get("reason") == "兑换码已过期 (超过首次兑换截止时间)":
                        await db_session.commit()
                    else:
                        await db_session.rollback()
                    return {"success": False, "error": validate_result.get("reason") or "兑换码不可用"}

                excluded_team_ids = await self._get_redeem_email_team_ids(db_session, normalized_email)
                redeem_team_type = await self._get_redeem_team_type(db_session)
                team = await self._reserve_next_available_team(db_session, excluded_team_ids, team_type=redeem_team_type)
                if not team:
                    await db_session.rollback()
                    pool_name = self._get_team_pool_label(redeem_team_type)
                    if excluded_team_ids:
                        return {"success": False, "error": f"该邮箱已加入所有可用{pool_name}，请使用其他邮箱或稍后再试"}
                    return {"success": False, "error": f"当前没有可用{pool_name}，请稍后再试"}

                redemption_code = await self._get_redemption_code(db_session, normalized_code)
                if not redemption_code or redemption_code.status != "unused":
                    await db_session.rollback()
                    return {"success": False, "error": "兑换码不可用或正在处理中"}

                redemption_code.status = "processing"
                job = InviteJob(
                    job_type=JOB_TYPE_REDEEM,
                    status=JOB_STATUS_QUEUED,
                    email=normalized_email,
                    code=normalized_code,
                    team_id=team.id,
                    idempotency_key=f"{JOB_TYPE_REDEEM}:{normalized_code}",
                    max_attempts=self._get_default_max_attempts(),
                    reservation_released=False,
                    created_at=get_now(),
                    updated_at=get_now(),
                )
                db_session.add(job)
                await db_session.commit()
                await db_session.refresh(job)
                return self.serialize_job(job)
            except Exception as exc:
                await db_session.rollback()
                logger.exception("创建兑换队列任务失败: %s", exc)
                return {"success": False, "error": f"创建兑换任务失败: {str(exc)}"}

    async def submit_warranty_job(
        self,
        db_session: AsyncSession,
        email: str,
        code: Optional[str] = None,
        entry_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        submitted_at = get_now()
        normalized_email = self._normalize_email(email)
        normalized_code = (code or "").strip()
        if not normalized_email:
            return {"success": False, "error": "邮箱不能为空"}

        async with self._submit_lock:
            try:
                validation_result = await self.warranty_service.validate_warranty_claim_input(
                    db_session=db_session,
                    email=normalized_email,
                    require_latest_team_banned=True,
                    code=normalized_code or None,
                    entry_id=entry_id,
                )
                if not validation_result.get("success"):
                    await self.warranty_service._record_warranty_claim_result(
                        db_session=db_session,
                        email=normalized_email,
                        submitted_at=submitted_at,
                        claim_status="failed",
                        before_team_info=validation_result.get("latest_team_info"),
                        failure_reason=validation_result.get("error"),
                    )
                    return validation_result

                warranty_entry: Optional[WarrantyEmailEntry] = validation_result.get("warranty_entry")
                selected_code = (
                    validation_result.get("warranty_code")
                    or (warranty_entry.last_redeem_code if warranty_entry else None)
                    or normalized_code
                )
                selected_entry_id = (
                    int(getattr(warranty_entry, "id"))
                    if warranty_entry and getattr(warranty_entry, "id", None)
                    else None
                )

                existing_job = await self._find_active_warranty_job(
                    db_session,
                    normalized_email,
                    selected_code or normalized_code or None,
                    entry_id=selected_entry_id,
                )
                if existing_job:
                    return self.serialize_job(existing_job)

                email_team_ids = await self._get_warranty_email_team_ids(db_session, normalized_email)
                team = await self._reserve_next_available_team(db_session, email_team_ids, team_type=TEAM_TYPE_STANDARD)
                if not team:
                    await db_session.rollback()
                    await self.warranty_service._record_warranty_claim_result(
                        db_session=db_session,
                        email=normalized_email,
                        submitted_at=submitted_at,
                        claim_status="failed",
                        before_team_info=validation_result.get("latest_team_info"),
                        failure_reason="当前没有可用的不同 Team，请稍后再试",
                    )
                    return {"success": False, "error": "当前没有可用的不同 Team，请稍后再试"}

                job = InviteJob(
                    job_type=JOB_TYPE_WARRANTY,
                    status=JOB_STATUS_QUEUED,
                    email=normalized_email,
                    code=selected_code,
                    warranty_entry_id=selected_entry_id,
                    team_id=team.id,
                    idempotency_key=f"{JOB_TYPE_WARRANTY}:{normalized_email}:entry:{selected_entry_id or selected_code or 'legacy'}",
                    max_attempts=self._get_default_max_attempts(),
                    reservation_released=False,
                    created_at=submitted_at,
                    updated_at=get_now(),
                )
                db_session.add(job)
                await db_session.commit()
                await db_session.refresh(job)
                return self.serialize_job(job)
            except Exception as exc:
                await db_session.rollback()
                logger.exception("创建质保队列任务失败: %s", exc)
                return {"success": False, "error": f"创建质保任务失败: {str(exc)}"}

    async def process_job_now(self, job_id: int) -> None:
        """测试/维护入口：立即处理指定任务。"""
        await self._process_job(job_id)

    async def recover_stale_processing_jobs(self) -> Dict[str, int]:
        timeout_seconds = max(int(settings.invite_queue_processing_timeout_seconds or 600), 1)
        cutoff = get_now() - timedelta(seconds=timeout_seconds)
        recovered = 0
        failed = 0

        async with AsyncSessionLocal() as db_session:
            result = await db_session.execute(
                select(InviteJob).where(
                    InviteJob.status == JOB_STATUS_PROCESSING,
                    InviteJob.started_at.is_not(None),
                    InviteJob.started_at <= cutoff,
                )
            )
            jobs = result.scalars().all()
            for job in jobs:
                await self._release_job_reservation(db_session, job)
                if int(job.attempt_count or 0) >= int(job.max_attempts or 5):
                    await self._mark_job_failed(
                        db_session,
                        job,
                        "任务处理超时次数过多，请稍后重试",
                        commit=False,
                    )
                    failed += 1
                else:
                    job.status = JOB_STATUS_QUEUED
                    job.team_id = None
                    job.started_at = None
                    job.error = "任务处理超时，已重新排队"
                    job.updated_at = get_now()
                    recovered += 1
            await db_session.commit()
        return {"recovered": recovered, "failed": failed}

    async def _worker_loop(self, worker_index: int) -> None:
        poll_interval = max(float(settings.invite_queue_poll_interval_seconds or 1), 0.2)
        while self._stop_event and not self._stop_event.is_set():
            try:
                await self.recover_stale_processing_jobs()
                job_id = await self._claim_next_job()
                if not job_id:
                    await asyncio.sleep(poll_interval)
                    continue
                logger.info("拉人队列 worker-%s 开始处理 job_id=%s", worker_index, job_id)
                await self._process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("拉人队列 worker-%s 执行失败: %s", worker_index, exc)
                await asyncio.sleep(poll_interval)

    async def _claim_next_job(self) -> Optional[int]:
        async with AsyncSessionLocal() as db_session:
            result = await db_session.execute(
                select(InviteJob)
                .where(InviteJob.status == JOB_STATUS_QUEUED)
                .order_by(InviteJob.created_at.asc(), InviteJob.id.asc())
                .limit(20)
            )
            for job in result.scalars().all():
                if job.team_id and self._team_locks[job.team_id].locked():
                    continue
                now = get_now()
                update_result = await db_session.execute(
                    update(InviteJob)
                    .where(InviteJob.id == job.id, InviteJob.status == JOB_STATUS_QUEUED)
                    .values(status=JOB_STATUS_PROCESSING, started_at=now, updated_at=now)
                )
                if update_result.rowcount == 1:
                    await db_session.commit()
                    return job.id
            await db_session.rollback()
            return None

    async def _process_job(self, job_id: int) -> None:
        excluded_team_ids: List[int] = []
        while True:
            async with AsyncSessionLocal() as db_session:
                job = await self.get_job(db_session, job_id)
                if not job or job.status in TERMINAL_JOB_STATUSES:
                    return

                if int(job.attempt_count or 0) >= int(job.max_attempts or 5):
                    await self._mark_job_failed(db_session, job, "任务重试次数过多，请稍后重试")
                    return

                if not job.team_id or job.reservation_released:
                    if job.job_type == JOB_TYPE_REDEEM:
                        email_team_ids = await self._get_redeem_email_team_ids(
                            db_session,
                            job.email,
                            exclude_job_id=job.id,
                        )
                        reservation_exclusions = [*excluded_team_ids, *email_team_ids]
                        target_team_type = await self._get_redeem_team_type(db_session)
                    else:
                        email_team_ids = await self._get_warranty_email_team_ids(
                            db_session,
                            job.email,
                            exclude_job_id=job.id,
                        )
                        reservation_exclusions = [*excluded_team_ids, *email_team_ids]
                        target_team_type = TEAM_TYPE_STANDARD

                    team = await self._reserve_next_available_team(db_session, reservation_exclusions, team_type=target_team_type)
                    if not team:
                        await self._mark_job_failed(db_session, job, f"当前没有可用{self._get_team_pool_label(target_team_type)}，请稍后再试")
                        return
                    job.team_id = team.id
                    job.reservation_released = False
                    job.updated_at = get_now()
                    await db_session.commit()

                team_id = int(job.team_id)

            async with self._team_locks[team_id]:
                async with AsyncSessionLocal() as db_session:
                    job = await self.get_job(db_session, job_id)
                    if not job or job.status in TERMINAL_JOB_STATUSES:
                        return
                    if job.status != JOB_STATUS_PROCESSING:
                        job.status = JOB_STATUS_PROCESSING
                        job.started_at = get_now()
                    job.attempt_count = int(job.attempt_count or 0) + 1
                    job.updated_at = get_now()
                    await db_session.commit()

                    outcome = await self._send_invite_for_job(db_session, job)
                    if outcome.get("success"):
                        await self._mark_job_success(db_session, job, outcome["payload"])
                        return

                    error_message = outcome.get("error") or "邀请失败"
                    if outcome.get("try_next_team") and int(job.attempt_count or 0) < int(job.max_attempts or 5):
                        excluded_team_ids.append(team_id)
                        await self._release_job_reservation(db_session, job)
                        job.team_id = None
                        job.status = JOB_STATUS_PROCESSING
                        job.error = error_message
                        job.updated_at = get_now()
                        await db_session.commit()
                        continue

                    await self._mark_job_failed(db_session, job, error_message)
                    return

    async def _send_invite_for_job(self, db_session: AsyncSession, job: InviteJob) -> Dict[str, Any]:
        team_id = int(job.team_id or 0)
        if team_id <= 0:
            return {"success": False, "try_next_team": True, "error": "未分配 Team"}

        refresh_source = SOURCE_USER_REDEEM if job.job_type == JOB_TYPE_REDEEM else SOURCE_USER_WARRANTY
        refresh_result = await self.team_service.refresh_team_state(team_id, db_session, source=refresh_source)
        await db_session.commit()
        if not refresh_result.get("success"):
            team = await db_session.get(Team, team_id)
            try_next_team = bool(
                refresh_result.get("allow_try_next_team")
                or (
                    team
                    and (
                        team.status in {"full", "expired", "error", "banned"}
                        or bool(getattr(team, "warranty_unavailable", False))
                    )
                )
            )
            return {
                "success": False,
                "try_next_team": try_next_team,
                "error": refresh_result.get("error") or "刷新 Team 状态失败",
            }

        team = await db_session.get(Team, team_id)
        if not team:
            return {"success": False, "try_next_team": True, "error": "目标 Team 不存在"}
        if team.status != "active":
            return {"success": False, "try_next_team": True, "error": f"目标 Team 不可用 ({team.status})"}
        if int(team.current_members or 0) >= int(team.max_members or 0):
            team.status = "full"
            await db_session.commit()
            return {"success": False, "try_next_team": True, "error": "该 Team 已满，请稍后再试"}

        if job.job_type == JOB_TYPE_REDEEM and await self._is_redeem_email_linked_to_team(
            db_session,
            job.email,
            team_id,
            exclude_job_id=job.id,
        ):
            return {
                "success": False,
                "try_next_team": True,
                "error": "该邮箱已在当前 Team 中，正在尝试其他 Team",
            }

        if job.job_type == JOB_TYPE_WARRANTY:
            existing_payload = await self._build_existing_warranty_payload(db_session, job)
            if existing_payload:
                return {"success": True, "payload": existing_payload}

        access_token = await self.team_service.ensure_access_token(team, db_session)
        if not access_token:
            team.status = "error"
            self.team_service._mark_warranty_team_unavailable(team, "获取 Team 访问权限失败，账户状态异常")
            await db_session.commit()
            return {"success": False, "try_next_team": True, "error": "获取 Team 访问权限失败，账户状态异常"}

        invite_result = await self.team_service.chatgpt_service.send_invite(
            access_token,
            team.account_id,
            job.email,
            db_session,
            identifier=team.email,
        )
        if not invite_result.get("success"):
            error_msg = str(invite_result.get("error") or "发送邀请失败")
            if self._is_already_member_error(error_msg):
                return {
                    "success": False,
                    "try_next_team": True,
                    "error": "该邮箱已在当前 Team 中，正在尝试其他 Team",
                }

            handled = await self.team_service._handle_api_error(invite_result, team, db_session)
            await db_session.commit()
            try_next = bool(
                handled
                and (
                    team.status in {"full", "expired", "error", "banned"}
                    or self.team_service._is_team_full_error_message(error_msg)
                    or self.team_service._is_risk_or_billing_error_message(error_msg)
                )
            )
            return {"success": False, "try_next_team": try_next, "error": error_msg}

        invite_data = invite_result.get("data") or {}
        if "account_invites" in invite_data and not invite_data.get("account_invites"):
            await self.team_service._handle_api_error(
                {"success": False, "error": "官方拦截下发(响应空列表)", "error_code": "ghost_success"},
                team,
                db_session,
            )
            await db_session.commit()
            return {
                "success": False,
                "try_next_team": True,
                "error": "Team账号受限: 官方拦截下发(响应空列表)，请检查账单/风控状态",
            }

        return {"success": True, "payload": await self._build_success_payload(db_session, job, team)}

    async def _get_redeem_email_team_ids(
        self,
        db_session: AsyncSession,
        email: str,
        exclude_job_id: Optional[int] = None,
    ) -> List[int]:
        """获取普通兑换中该邮箱已加入、已邀请或正在预占的 Team。"""
        normalized_email = self._normalize_email(email)
        if not normalized_email:
            return []

        team_ids: List[int] = []

        snapshot_result = await db_session.execute(
            select(TeamMemberSnapshot.team_id).where(
                TeamMemberSnapshot.email == normalized_email,
            )
        )
        team_ids.extend(int(team_id) for team_id in snapshot_result.scalars().all() if team_id)

        job_stmt = select(InviteJob.team_id).where(
            InviteJob.job_type == JOB_TYPE_REDEEM,
            InviteJob.email == normalized_email,
            InviteJob.status.in_(ACTIVE_JOB_STATUSES),
            InviteJob.team_id.is_not(None),
            InviteJob.reservation_released.is_(False),
        )
        if exclude_job_id:
            job_stmt = job_stmt.where(InviteJob.id != int(exclude_job_id))

        job_result = await db_session.execute(job_stmt)
        team_ids.extend(int(team_id) for team_id in job_result.scalars().all() if team_id)

        return list(dict.fromkeys(team_ids))

    async def _is_redeem_email_linked_to_team(
        self,
        db_session: AsyncSession,
        email: str,
        team_id: int,
        exclude_job_id: Optional[int] = None,
    ) -> bool:
        team_ids = await self._get_redeem_email_team_ids(
            db_session,
            email,
            exclude_job_id=exclude_job_id,
        )
        return int(team_id) in team_ids

    async def _get_warranty_email_team_ids(
        self,
        db_session: AsyncSession,
        email: str,
        exclude_job_id: Optional[int] = None,
    ) -> List[int]:
        """获取该邮箱已质保加入或正在质保预占的 Team，避免同邮箱多订单进入同一 Team。"""
        normalized_email = self._normalize_email(email)
        if not normalized_email:
            return []

        team_ids: List[int] = []
        record_result = await db_session.execute(
            select(RedemptionRecord.team_id).where(
                func.lower(func.trim(RedemptionRecord.email)) == normalized_email,
                RedemptionRecord.is_warranty_redemption.is_(True),
                RedemptionRecord.team_id.is_not(None),
            )
        )
        team_ids.extend(int(team_id) for team_id in record_result.scalars().all() if team_id)

        job_stmt = select(InviteJob.team_id).where(
            InviteJob.job_type == JOB_TYPE_WARRANTY,
            InviteJob.email == normalized_email,
            InviteJob.status.in_(ACTIVE_JOB_STATUSES),
            InviteJob.team_id.is_not(None),
            InviteJob.reservation_released.is_(False),
        )
        if exclude_job_id:
            job_stmt = job_stmt.where(InviteJob.id != int(exclude_job_id))

        job_result = await db_session.execute(job_stmt)
        team_ids.extend(int(team_id) for team_id in job_result.scalars().all() if team_id)

        return list(dict.fromkeys(team_ids))

    async def _build_existing_warranty_payload(
        self,
        db_session: AsyncSession,
        job: InviteJob,
    ) -> Optional[Dict[str, Any]]:
        warranty_entry = await self.warranty_service.get_warranty_email_entry_by_id(
            db_session,
            job.warranty_entry_id,
            email=job.email,
        )
        if not warranty_entry:
            warranty_entry = await self.warranty_service.find_warranty_email_entry_for_order(
                db_session,
                job.email,
                code=job.code,
            )
        selected_code = (job.code or "").strip()
        if not warranty_entry and not selected_code:
            return None

        existing_team = await self.warranty_service._find_existing_warranty_team_from_entry(db_session, warranty_entry)
        if not existing_team:
            return None

        before_team_info = await self._load_before_team_info(db_session, job.email, selected_code or None)

        if warranty_entry and warranty_entry.last_warranty_team_id != existing_team.id:
            warranty_entry.last_warranty_team_id = existing_team.id
            await db_session.commit()
            await db_session.refresh(warranty_entry)
        order_info = (
            await self.warranty_service.get_warranty_order_info(db_session, job.email, selected_code, warranty_entry)
            if selected_code
            else None
        )

        await self.warranty_service._record_warranty_claim_result(
            db_session=db_session,
            email=job.email,
            submitted_at=job.created_at or get_now(),
            claim_status="success",
            before_team_info=before_team_info,
            after_team=existing_team,
        )
        return {
            "success": True,
            "message": "质保邀请已存在，请直接查收邮箱中的邀请邮件。",
            "team_info": self._serialize_team_info(existing_team),
            "warranty_info": (
                order_info.get("warranty_info")
                if order_info
                else self.warranty_service.serialize_warranty_email_entry(warranty_entry) if warranty_entry else {}
            ),
            "_skip_member_increment": True,
        }

    async def _build_success_payload(
        self,
        db_session: AsyncSession,
        job: InviteJob,
        team: Team,
    ) -> Dict[str, Any]:
        if job.job_type == JOB_TYPE_WARRANTY:
            warranty_entry = await self.warranty_service.get_warranty_email_entry_by_id(
                db_session,
                job.warranty_entry_id,
                email=job.email,
            )
            if not warranty_entry:
                warranty_entry = await self.warranty_service.find_warranty_email_entry_for_order(
                    db_session,
                    job.email,
                    code=job.code,
                )
            selected_code = (job.code or "").strip()
            if not warranty_entry and not selected_code:
                return {"success": False, "error": "质保邮箱记录不存在"}
            before_team_info = await self._load_before_team_info(db_session, job.email, selected_code or None)
            await self.warranty_service._record_warranty_claim_success(
                db_session=db_session,
                entry=warranty_entry,
                email=job.email,
                team=team,
                redeem_code=selected_code or None,
            )
            order_info = (
                await self.warranty_service.get_warranty_order_info(db_session, job.email, selected_code, warranty_entry)
                if selected_code
                else None
            )
            await self.warranty_service._record_warranty_claim_result(
                db_session=db_session,
                email=job.email,
                submitted_at=job.created_at or get_now(),
                claim_status="success",
                before_team_info=before_team_info,
                after_team=team,
            )
            return {
                "success": True,
                "message": "质保邀请发送成功，请查收邮箱。",
                "team_info": self._serialize_team_info(team),
                "warranty_info": (
                    order_info.get("warranty_info")
                    if order_info
                    else self.warranty_service.serialize_warranty_email_entry(warranty_entry) if warranty_entry else {}
                ),
            }

        redemption_code = await self._get_redemption_code(db_session, job.code or "")
        if not redemption_code:
            return {"success": False, "error": "兑换码不存在"}

        redemption_code.status = "used"
        redemption_code.used_by_email = job.email
        redemption_code.used_team_id = team.id
        redemption_code.used_at = get_now()
        if redemption_code.has_warranty:
            days = redemption_code.warranty_days if redemption_code.warranty_days is not None else 30
            redemption_code.warranty_expires_at = get_now() + timedelta(days=days)

        db_session.add(
            RedemptionRecord(
                email=job.email,
                code=job.code or "",
                team_id=team.id,
                account_id=team.account_id,
                is_warranty_redemption=bool(redemption_code.has_warranty),
            )
        )
        await self.warranty_service.sync_warranty_email_entry_after_redeem(
            db_session=db_session,
            email=job.email,
            redeem_code=job.code or "",
            has_warranty_code=bool(redemption_code.has_warranty),
            team_id=team.id,
        )
        await db_session.flush()
        await email_whitelist_service.sync_from_dependency_sources(db_session, commit=False)
        await db_session.commit()

        return {
            "success": True,
            "message": "兑换成功！邀请链接已发送至您的邮箱，请及时查收。",
            "team_info": self._serialize_team_info(team),
        }

    async def _mark_job_success(self, db_session: AsyncSession, job: InviteJob, payload: Dict[str, Any]) -> None:
        if payload.get("success") is False:
            await self._mark_job_failed(db_session, job, payload.get("error") or "任务处理失败")
            return

        skip_member_increment = bool(payload.pop("_skip_member_increment", False))
        source = SOURCE_USER_REDEEM if job.job_type == JOB_TYPE_REDEEM else SOURCE_USER_WARRANTY
        post_sync = await self.team_service.refresh_team_state(int(job.team_id), db_session, source=source)
        await db_session.commit()

        job = await self.get_job(db_session, int(job.id))
        if not job:
            return
        team = await db_session.get(Team, int(job.team_id)) if job.team_id else None
        await self._release_job_reservation(db_session, job)
        if team and not skip_member_increment:
            member_emails = [self._normalize_email(email) for email in post_sync.get("member_emails", [])]
            if self._normalize_email(job.email) not in member_emails and int(team.current_members or 0) < int(team.max_members or 0):
                team.current_members = min(int(team.max_members or 0), int(team.current_members or 0) + 1)
            if int(team.current_members or 0) >= int(team.max_members or 0):
                team.status = "full"
            elif team.status == "full":
                team.status = "active"

        job.status = JOB_STATUS_SUCCESS
        job.error = None
        job.result_payload = self._encode_payload(payload)
        job.completed_at = get_now()
        job.updated_at = get_now()
        await db_session.commit()

    async def _mark_job_failed(
        self,
        db_session: AsyncSession,
        job: InviteJob,
        error: str,
        commit: bool = True,
    ) -> None:
        await self._release_job_reservation(db_session, job)
        if job.job_type == JOB_TYPE_REDEEM and job.code:
            redemption_code = await self._get_redemption_code(db_session, job.code)
            if redemption_code and redemption_code.status == "processing":
                redemption_code.status = "unused"
        if job.job_type == JOB_TYPE_WARRANTY:
            await self.warranty_service._record_warranty_claim_result(
                db_session=db_session,
                email=job.email,
                submitted_at=job.created_at or get_now(),
                claim_status="failed",
                before_team_info=await self._load_before_team_info(db_session, job.email, job.code),
                failure_reason=error,
            )
            job = await self.get_job(db_session, int(job.id)) or job

        job.status = JOB_STATUS_FAILED
        job.error = error
        job.result_payload = self._encode_payload({"success": False, "error": error})
        job.completed_at = get_now()
        job.updated_at = get_now()
        if commit:
            await db_session.commit()

    async def _reserve_next_available_team(
        self,
        db_session: AsyncSession,
        exclude_team_ids: Optional[List[int]] = None,
        team_type: Optional[str] = TEAM_TYPE_STANDARD,
    ) -> Optional[Team]:
        exclude_team_ids = list(dict.fromkeys([int(team_id) for team_id in exclude_team_ids or [] if team_id]))
        active_window_team_ids = await self._get_active_window_team_ids(db_session, team_type=team_type)
        candidate_team_ids = [
            team_id
            for team_id in active_window_team_ids
            if team_id not in exclude_team_ids
        ]
        if not candidate_team_ids:
            return None

        capacity_expr = func.coalesce(Team.current_members, 0) + func.coalesce(Team.reserved_members, 0)
        stmt = select(Team.id).where(
            Team.id.in_(candidate_team_ids),
            Team.status == "active",
            capacity_expr < Team.max_members,
            Team.import_status == IMPORT_STATUS_CLASSIFIED,
            or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None)),
        )
        if team_type:
            stmt = stmt.where(Team.team_type == team_type)
        stmt = stmt.order_by(
            func.coalesce(Team.reserved_members, 0).asc(),
            func.coalesce(Team.current_members, 0).asc(),
            Team.id.asc(),
        )

        result = await db_session.execute(stmt)
        for team_id in result.scalars().all():
            update_stmt = update(Team).where(
                Team.id == int(team_id),
                Team.status == "active",
                (func.coalesce(Team.current_members, 0) + func.coalesce(Team.reserved_members, 0)) < Team.max_members,
                Team.import_status == IMPORT_STATUS_CLASSIFIED,
                or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None)),
            )
            if team_type:
                update_stmt = update_stmt.where(Team.team_type == team_type)
            update_result = await db_session.execute(
                update_stmt.values(reserved_members=func.coalesce(Team.reserved_members, 0) + 1)
            )
            if update_result.rowcount == 1:
                await db_session.flush()
                team = await db_session.get(Team, int(team_id))
                if team:
                    await db_session.refresh(team)
                    return team
        return None

    async def _get_active_window_team_ids(
        self,
        db_session: AsyncSession,
        team_type: Optional[str] = TEAM_TYPE_STANDARD,
    ) -> List[int]:
        capacity_expr = func.coalesce(Team.current_members, 0) + func.coalesce(Team.reserved_members, 0)
        stmt = (
            select(Team.id)
            .where(
                Team.status == "active",
                capacity_expr < Team.max_members,
                Team.import_status == IMPORT_STATUS_CLASSIFIED,
                or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None)),
            )
            .order_by(Team.id.asc())
            .limit(self._get_active_team_limit())
        )
        if team_type:
            stmt = stmt.where(Team.team_type == team_type)
        result = await db_session.execute(stmt)
        return [int(team_id) for team_id in result.scalars().all() if team_id]

    async def _release_job_reservation(self, db_session: AsyncSession, job: InviteJob) -> None:
        if not job.team_id or job.reservation_released:
            return
        await db_session.execute(
            update(Team)
            .where(Team.id == int(job.team_id))
            .values(
                reserved_members=func.max(func.coalesce(Team.reserved_members, 0) - 1, 0)
            )
        )
        job.reservation_released = True
        job.updated_at = get_now()
        await db_session.flush()

    async def _find_active_redeem_job(self, db_session: AsyncSession, code: str) -> Optional[InviteJob]:
        result = await db_session.execute(
            select(InviteJob).where(
                InviteJob.job_type == JOB_TYPE_REDEEM,
                InviteJob.code == code,
                InviteJob.status.in_(ACTIVE_JOB_STATUSES),
            ).order_by(InviteJob.created_at.desc(), InviteJob.id.desc())
        )
        return result.scalars().first()

    async def _find_active_warranty_job(
        self,
        db_session: AsyncSession,
        email: str,
        code: Optional[str] = None,
        entry_id: Optional[int] = None,
    ) -> Optional[InviteJob]:
        stmt = select(InviteJob).where(
            InviteJob.job_type == JOB_TYPE_WARRANTY,
            InviteJob.email == email,
            InviteJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        try:
            safe_entry_id = int(entry_id or 0)
        except (TypeError, ValueError):
            safe_entry_id = 0
        if safe_entry_id > 0:
            stmt = stmt.where(InviteJob.warranty_entry_id == safe_entry_id)
        else:
            stmt = stmt.where(InviteJob.warranty_entry_id.is_(None))
        normalized_code = (code or "").strip()
        if normalized_code:
            stmt = stmt.where(InviteJob.code == normalized_code)
        result = await db_session.execute(
            stmt.order_by(InviteJob.created_at.desc(), InviteJob.id.desc())
        )
        return result.scalars().first()

    async def _get_redemption_code(self, db_session: AsyncSession, code: str) -> Optional[RedemptionCode]:
        result = await db_session.execute(select(RedemptionCode).where(RedemptionCode.code == code))
        return result.scalar_one_or_none()

    async def _load_before_team_info(
        self,
        db_session: AsyncSession,
        email: str,
        code: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            normalized_code = (code or "").strip()
            if normalized_code:
                warranty_entry = await self.warranty_service.get_warranty_email_entry(db_session, email)
                latest_contexts = await self.warranty_service._load_warranty_order_contexts_for_email(
                    db_session,
                    email,
                    warranty_entry=warranty_entry,
                    target_code=normalized_code,
                )
                latest_context = latest_contexts[0] if latest_contexts else None
                if not latest_context:
                    latest_context = await self.warranty_service._load_latest_team_context_for_email(db_session, email)
            else:
                latest_context = await self.warranty_service._load_latest_team_context_for_email(db_session, email)
            if latest_context:
                return latest_context.get("team_info")
        except Exception as exc:
            logger.warning("读取质保提交前 Team 信息失败: email=%s error=%s", email, exc)
        return None

    def _serialize_team_info(self, team: Team) -> Dict[str, Any]:
        return {
            "id": team.id,
            "team_name": team.team_name,
            "email": team.email,
            "expires_at": team.expires_at.isoformat() if team.expires_at else None,
        }

    def _get_job_message(self, job: InviteJob) -> str:
        if job.status == JOB_STATUS_QUEUED:
            return "请求已进入队列，请保持页面开启等待处理。"
        if job.status == JOB_STATUS_PROCESSING:
            return "正在为您处理邀请，请勿重复提交。"
        if job.status == JOB_STATUS_SUCCESS:
            return "处理成功。"
        return job.error or "处理失败，请稍后重试。"

    def _normalize_email(self, email: str) -> str:
        return (email or "").strip().lower()

    def _is_already_member_error(self, error_msg: str) -> bool:
        normalized_error = (error_msg or "").lower()
        return any(keyword in normalized_error for keyword in ["already in workspace", "already in team", "already a member"])

    def _encode_payload(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)

    def _decode_payload(self, payload: Optional[str]) -> Optional[Dict[str, Any]]:
        if not payload:
            return None
        try:
            decoded = json.loads(payload)
            return decoded if isinstance(decoded, dict) else None
        except Exception:
            return None


invite_queue_service = InviteQueueService()
