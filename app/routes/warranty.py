"""
质保相关路由
处理用户质保查询请求
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.warranty import warranty_service

router = APIRouter(
    prefix="/warranty",
    tags=["warranty"]
)


class WarrantyCheckRequest(BaseModel):
    """质保查询请求"""
    email: Optional[EmailStr] = None
    code: Optional[str] = None


class WarrantyCheckRecord(BaseModel):
    """质保查询单条记录"""
    code: str
    has_warranty: bool
    warranty_valid: bool
    warranty_expires_at: Optional[str]
    status: str
    used_at: Optional[str]
    team_id: Optional[int]
    team_name: Optional[str]
    team_status: Optional[str]
    team_expires_at: Optional[str]
    email: Optional[str] = None
    device_code_auth_enabled: bool = False


class WarrantyCheckResponse(BaseModel):
    """质保查询响应"""
    success: bool
    has_warranty: bool
    warranty_valid: bool
    warranty_expires_at: Optional[str]
    banned_teams: list
    can_reuse: bool
    original_code: Optional[str]
    records: list[WarrantyCheckRecord] = []
    message: Optional[str]
    error: Optional[str]


@router.post("/check", response_model=WarrantyCheckResponse)
async def check_warranty(
    request: WarrantyCheckRequest,
    db_session: AsyncSession = Depends(get_db)
):
    """
    前台质保查询暂时停用
    """
    raise HTTPException(
        status_code=503,
        detail="前台质保查询暂时停用。质保期间如果您使用兑换码加入的 Team 被封号，请在质保期内（一个月）联系客服，再次获取兑换码。"
    )


class EnableDeviceAuthRequest(BaseModel):
    """开启设备身份验证请求"""
    code: str
    email: str
    team_id: int


class WarrantyClaimRequest(BaseModel):
    ordinary_code: str
    email: EmailStr
    super_code: str


@router.post("/claim")
async def claim_warranty(
    request: WarrantyClaimRequest,
    db_session: AsyncSession = Depends(get_db)
):
    result = await warranty_service.claim_warranty_invite(
        db_session=db_session,
        ordinary_code=request.ordinary_code,
        email=request.email,
        super_code=request.super_code
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "校验失败或当前无法提供质保服务")

    return result


@router.post("/enable-device-auth")
async def enable_device_auth(
    request: EnableDeviceAuthRequest,
    db_session: AsyncSession = Depends(get_db)
):
    """
    用户一键开启设备身份验证
    """
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
