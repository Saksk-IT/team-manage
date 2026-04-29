"""
质保相关路由
处理用户质保查询请求
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.invite_queue import invite_queue_service
from app.services.settings import settings_service
from app.services.warranty import warranty_service

router = APIRouter(
    prefix="/warranty",
    tags=["warranty"]
)


async def ensure_warranty_service_enabled(db_session: AsyncSession) -> None:
    config = await settings_service.get_warranty_service_config(db_session)
    if not config.get("enabled"):
        raise HTTPException(status_code=404, detail="前台质保服务未开启")


class WarrantyCheckRequest(BaseModel):
    """质保查询请求"""
    email: EmailStr


class WarrantyLatestTeamInfo(BaseModel):
    """最近加入 Team 信息"""
    id: int
    team_name: Optional[str]
    email: Optional[str]
    account_id: Optional[str]
    status: str
    status_label: str
    redeemed_at: Optional[str]
    expires_at: Optional[str]
    code: Optional[str]
    is_warranty_redemption: bool = False


class WarrantyCheckResponse(BaseModel):
    """质保查询响应"""
    success: bool
    can_claim: bool
    latest_team: Optional[WarrantyLatestTeamInfo] = None
    warranty_info: Optional[dict] = None
    warranty_orders: List[dict] = Field(default_factory=list)
    message: Optional[str]
    error: Optional[str]


@router.post("/check", response_model=WarrantyCheckResponse)
async def check_warranty(
    request: WarrantyCheckRequest,
    db_session: AsyncSession = Depends(get_db)
):
    """
    查询质保邮箱最近加入的 Team 状态。
    """
    await ensure_warranty_service_enabled(db_session)
    result = await warranty_service.get_warranty_claim_status(
        db_session=db_session,
        email=request.email
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "状态查询失败")

    return {
        "success": True,
        "can_claim": result.get("can_claim", False),
        "latest_team": result.get("latest_team"),
        "warranty_info": result.get("warranty_info"),
        "warranty_orders": result.get("warranty_orders", []),
        "message": result.get("message"),
        "error": None,
    }


class EnableDeviceAuthRequest(BaseModel):
    """开启设备身份验证请求"""
    code: str
    email: str
    team_id: int


class WarrantyClaimRequest(BaseModel):
    email: EmailStr
    code: Optional[str] = None
    entry_id: Optional[int] = Field(None, gt=0)


@router.post("/claim")
async def claim_warranty(
    request: WarrantyClaimRequest,
    db_session: AsyncSession = Depends(get_db)
):
    await ensure_warranty_service_enabled(db_session)
    result = await invite_queue_service.submit_warranty_job(
        db_session=db_session,
        email=request.email,
        code=request.code,
        entry_id=request.entry_id
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "校验失败或当前无法提供质保服务")

    return result


@router.post("/fake-success/complete")
async def complete_fake_warranty_success(
    db_session: AsyncSession = Depends(get_db)
):
    """
    前台质保模拟成功模式下，扣减并返回持久化展示席位。
    """
    await ensure_warranty_service_enabled(db_session)
    config = await settings_service.get_warranty_fake_success_config(db_session)
    if not config.get("enabled"):
        raise HTTPException(status_code=400, detail="前台质保模拟成功模式未启用")

    remaining_spots = await settings_service.decrement_warranty_fake_success_remaining_spots(db_session)
    return {
        "success": True,
        "remaining_spots": remaining_spots
    }


@router.post("/fake-success/validate")
async def validate_fake_warranty_success(
    request: WarrantyClaimRequest,
    db_session: AsyncSession = Depends(get_db)
):
    """
    前台质保模拟成功模式下的基础输入校验。
    """
    await ensure_warranty_service_enabled(db_session)
    config = await settings_service.get_warranty_fake_success_config(db_session)
    if not config.get("enabled"):
        raise HTTPException(status_code=400, detail="前台质保模拟成功模式未启用")

    result = await warranty_service.validate_warranty_claim_input(
        db_session=db_session,
        email=request.email,
        require_latest_team_banned=False,
        code=request.code,
        entry_id=request.entry_id
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "校验失败")

    return {
        "success": True,
        "message": "校验通过"
    }


@router.post("/enable-device-auth")
async def enable_device_auth(
    request: EnableDeviceAuthRequest,
    db_session: AsyncSession = Depends(get_db)
):
    """
    用户一键开启设备身份验证
    """
    await ensure_warranty_service_enabled(db_session)
    from app.services.team import team_service
    from sqlalchemy import select
    from app.models import RedemptionRecord

    try:
        # 1. 验证用户是否有记录在该 Team
        stmt = select(RedemptionRecord).where(
            RedemptionRecord.code == request.code,
            RedemptionRecord.email == request.email,
            RedemptionRecord.team_id == request.team_id
        )
        result = await db_session.execute(stmt)
        record = result.scalar_one_or_none()
        
        if not record:
            raise HTTPException(
                status_code=403,
                detail="未找到相关的兑换记录，无法进行该操作"
            )
            
        # 2. 调用 TeamService 开启
        # 注意：这里我们使用已经实现的 enable_device_code_auth
        res = await team_service.enable_device_code_auth(request.team_id, db_session)
        
        if not res.get("success"):
            raise HTTPException(
                status_code=500,
                detail=res.get("error", "开启失败")
            )
            
        return {"success": True, "message": "设备代码身份验证开启成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"开启失败: {str(e)}"
        )
