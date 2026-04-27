"""
前台拉人任务查询路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.invite_queue import invite_queue_service

router = APIRouter(
    prefix="/invite-jobs",
    tags=["invite-jobs"],
)


@router.get("/{job_id}")
async def get_invite_job_status(
    job_id: int,
    db_session: AsyncSession = Depends(get_db),
):
    job = await invite_queue_service.get_job(db_session, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    return invite_queue_service.serialize_job(job)
