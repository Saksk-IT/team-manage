"""
Team 自动刷新服务
负责后台定时同步 Team 状态，避免列表页显示过期库存状态。
"""
import asyncio
import logging
import math
from datetime import timedelta
from typing import Optional, List

from sqlalchemy import case, or_, select

from app.database import AsyncSessionLocal
from app.models import Team
from app.services.settings import settings_service
from app.services.team import (
    IMPORT_STATUS_CLASSIFIED,
    team_service,
)
from app.services.team_refresh_record import SOURCE_AUTO, team_refresh_record_service
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class TeamAutoRefreshService:
    """后台 Team 自动刷新服务"""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._run_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="team-auto-refresh"
        )
        logger.info("Team 自动刷新服务已启动")

    async def stop(self) -> None:
        task = self._task
        stop_event = self._stop_event

        self._task = None
        self._stop_event = None

        if stop_event:
            stop_event.set()

        if not task:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        logger.info("Team 自动刷新服务已停止")

    async def _run_loop(self) -> None:
        while True:
            interval_minutes = settings_service.DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES
            try:
                interval_minutes = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Team 自动刷新循环执行失败: %s", exc)

            stop_event = self._stop_event
            if not stop_event:
                return

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=max(interval_minutes, 1) * 60
                )
                return
            except asyncio.TimeoutError:
                continue

    async def _get_runtime_config(self) -> dict:
        async with AsyncSessionLocal() as session:
            return await settings_service.get_team_auto_refresh_config(session)

    async def _get_refreshable_team_ids(
        self,
        *,
        interval_minutes: int,
        limit: int = 1,
    ) -> List[int]:
        refresh_cutoff = get_now() - timedelta(minutes=max(int(interval_minutes or 1), 1))
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Team.id)
                .where(Team.status != "banned")
                .where(Team.import_status == IMPORT_STATUS_CLASSIFIED)
                .where(or_(Team.last_refresh_at.is_(None), Team.last_refresh_at <= refresh_cutoff))
                .order_by(
                    case((Team.last_refresh_at.is_(None), 0), else_=1).asc(),
                    Team.last_refresh_at.asc(),
                    Team.id.asc(),
                )
                .limit(max(int(limit or 1), 1))
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _get_next_due_delay_minutes(self, *, interval_minutes: int) -> int:
        now = get_now()
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Team.last_refresh_at)
                .where(Team.status != "banned")
                .where(Team.import_status == IMPORT_STATUS_CLASSIFIED)
                .where(Team.last_refresh_at.is_not(None))
                .order_by(Team.last_refresh_at.asc(), Team.id.asc())
                .limit(1)
            )
            result = await session.execute(stmt)
            oldest_refresh_at = result.scalar_one_or_none()

        if not oldest_refresh_at:
            return interval_minutes

        next_due_at = oldest_refresh_at + timedelta(minutes=max(int(interval_minutes or 1), 1))
        delay_seconds = (next_due_at - now).total_seconds()
        if delay_seconds <= 0:
            return 1
        return min(
            max(math.ceil(delay_seconds / 60), 1),
            max(int(interval_minutes or 1), 1),
        )

    async def _record_unhandled_refresh_failure(self, team_id: int, exc: Exception) -> None:
        """
        兜底记录自动刷新未捕获异常。

        refresh_team_state 正常会写入刷新记录；但如果它自身抛出异常，
        调度器仍需留下失败记录并重置该 Team 计时，避免后台看不到自动
        刷新痕迹且下一轮反复撞同一个异常。
        """
        safe_error = f"自动刷新执行异常: {exc.__class__.__name__}，请查看服务日志获取详细堆栈"

        try:
            async with AsyncSessionLocal() as session:
                team = await session.get(Team, team_id)
                if not team:
                    logger.warning("自动刷新异常记录跳过: Team %s 不存在", team_id)
                    return

                team.last_refresh_at = get_now()
                await team_refresh_record_service.create_record(
                    db_session=session,
                    team=team,
                    source=SOURCE_AUTO,
                    force_refresh=False,
                    refresh_result={
                        "success": False,
                        "message": None,
                        "error": safe_error,
                        "error_code": "auto_refresh_exception",
                    },
                )
                await session.commit()
        except Exception as record_error:
            logger.exception(
                "写入自动刷新异常记录失败: team_id=%s error=%s",
                team_id,
                record_error,
            )

    async def run_once(self) -> int:
        """
        执行一轮自动刷新。

        Returns:
            下一轮等待分钟数
        """
        async with self._run_lock:
            config = await self._get_runtime_config()
            interval_minutes = config["interval_minutes"]

            if not config["enabled"]:
                logger.debug("Team 自动刷新已关闭，跳过本轮同步")
                return interval_minutes

            team_ids = await self._get_refreshable_team_ids(
                interval_minutes=interval_minutes,
                limit=1,
            )
            if not team_ids:
                next_delay_minutes = await self._get_next_due_delay_minutes(
                    interval_minutes=interval_minutes,
                )
                logger.debug(
                    "没有到达自动刷新间隔的 Team，下一次检查将在 %s 分钟后执行",
                    next_delay_minutes,
                )
                return next_delay_minutes

            logger.info(
                "开始自动刷新到期 Team 状态: 本轮 %s 个账号，间隔 %s 分钟",
                len(team_ids),
                interval_minutes
            )

            success_count = 0
            failed_count = 0

            for team_id in team_ids:
                if self._stop_event and self._stop_event.is_set():
                    logger.info("Team 自动刷新收到停止信号，中断当前轮次")
                    break

                try:
                    async with AsyncSessionLocal() as session:
                        result = await team_service.refresh_team_state(
                            team_id,
                            session,
                            force_refresh=False,
                            source=SOURCE_AUTO,
                        )
                        await session.commit()

                    if result.get("success"):
                        success_count += 1
                    else:
                        failed_count += 1
                        logger.warning(
                            "自动刷新 Team %s 失败: %s",
                            team_id,
                            result.get("error") or "未知错误"
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    failed_count += 1
                    logger.exception("自动刷新 Team %s 异常: %s", team_id, exc)
                    await self._record_unhandled_refresh_failure(team_id, exc)

            logger.info(
                "自动刷新 Team 轮次完成: 成功 %s，失败 %s",
                success_count,
                failed_count
            )
            return interval_minutes


team_auto_refresh_service = TeamAutoRefreshService()
