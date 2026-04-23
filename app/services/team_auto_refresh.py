"""
Team 自动刷新服务
负责后台定时同步 Team 状态，避免列表页显示过期库存状态。
"""
import asyncio
import logging
from typing import Optional, List

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Team
from app.services.settings import settings_service
from app.services.team import (
    TEAM_TYPE_STANDARD,
    TEAM_TYPE_WARRANTY,
    team_service,
)

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

    async def _get_refreshable_team_ids(self) -> List[int]:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(Team.id)
                .where(Team.status != "banned")
                .where(Team.team_type.in_([TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY]))
                .order_by(Team.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

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

            team_ids = await self._get_refreshable_team_ids()
            if not team_ids:
                logger.debug("没有可自动同步的 Team，跳过本轮同步")
                return interval_minutes

            logger.info(
                "开始自动刷新 Team 状态: 共 %s 个账号，间隔 %s 分钟",
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
                        result = await team_service.sync_team_info(
                            team_id,
                            session,
                            force_refresh=False,
                            enforce_bound_email_cleanup=True,
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

            logger.info(
                "自动刷新 Team 轮次完成: 成功 %s，失败 %s",
                success_count,
                failed_count
            )
            return interval_minutes


team_auto_refresh_service = TeamAutoRefreshService()
