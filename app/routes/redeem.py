"""
兑换路由
处理用户兑换码验证和加入 Team 的请求
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.redeem_flow import redeem_flow_service
from app.services.redemption import redemption_service
from app.services.invite_queue import invite_queue_service

logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/redeem",
    tags=["redeem"]
)


# 请求模型
class VerifyCodeRequest(BaseModel):
    """验证兑换码请求"""
    code: str = Field(..., description="兑换码", min_length=1)


class BoundEmailLookupRequest(BaseModel):
    """前台查询绑定邮箱请求"""
    code: str = Field(..., description="兑换码", min_length=1)


class BoundEmailWithdrawRequest(BaseModel):
    """前台撤销绑定邮箱请求"""
    code: str = Field(..., description="兑换码", min_length=1)


class RedeemRequest(BaseModel):
    """兑换请求"""
    email: EmailStr = Field(..., description="用户邮箱")
    code: str = Field(..., description="兑换码", min_length=1)
    team_id: Optional[int] = Field(None, description="Team ID (可选，不提供则自动选择)")


# 响应模型
class TeamInfo(BaseModel):
    """Team 信息"""
    id: int
    team_name: str
    current_members: int
    max_members: int
    expires_at: Optional[str]
    subscription_plan: Optional[str]


class VerifyCodeResponse(BaseModel):
    """验证兑换码响应"""
    success: bool
    valid: bool
    reason: Optional[str] = None
    teams: List[TeamInfo] = []
    error: Optional[str] = None


class RedeemResponse(BaseModel):
    """兑换响应"""
    success: bool
    queued: bool = False
    job_id: Optional[int] = None
    job_status: Optional[str] = None
    poll_after_ms: Optional[int] = None
    message: Optional[str] = None
    team_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class BoundEmailLookupResponse(BaseModel):
    """前台查询绑定邮箱响应"""
    success: bool
    found: bool
    bound: bool
    email: Optional[str] = None
    code_status: Optional[str] = None
    code_status_label: Optional[str] = None
    used_at: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class BoundEmailWithdrawResponse(BaseModel):
    """前台撤销绑定邮箱响应"""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


CODE_STATUS_LABELS = {
    "unused": "未使用",
    "used": "已使用",
    "expired": "已过期",
    "processing": "处理中",
    "warranty_active": "质保中",
}

FRONT_WITHDRAW_DISABLED_MESSAGE = "前台自助撤销已关闭，撤销请联系客服处理。"


def _get_code_status_label(code_status: Optional[str]) -> Optional[str]:
    if not code_status:
        return None
    return CODE_STATUS_LABELS.get(code_status, code_status)


@router.post("/verify", response_model=VerifyCodeResponse)
async def verify_code(
    request: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    验证兑换码并返回可用 Team 列表

    Args:
        request: 验证请求
        db: 数据库会话

    Returns:
        验证结果和可用 Team 列表
    """
    try:
        logger.info(f"验证兑换码请求: {request.code}")

        result = await redeem_flow_service.verify_code_and_get_teams(
            request.code,
            db
        )

        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result["error"]
            )

        return VerifyCodeResponse(
            success=result.get("success", False),
            valid=result.get("valid", False),
            reason=result.get("reason"),
            teams=[TeamInfo(**team) for team in result.get("teams", [])],
            error=result.get("error")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证兑换码失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"验证失败: {str(e)}"
        )


@router.post("/bound-email", response_model=BoundEmailLookupResponse)
async def lookup_bound_email(
    request: BoundEmailLookupRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    根据兑换码查询当前绑定邮箱（前台返回完整邮箱）。
    """
    code = (request.code or "").strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="兑换码不能为空"
        )

    try:
        logger.info("前台查询兑换码绑定邮箱: %s", code)

        result = await redemption_service.lookup_code_binding_email(
            code=code,
            db_session=db
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error") or "查询绑定邮箱失败"
            )

        used_by_email = result.get("used_by_email")

        return BoundEmailLookupResponse(
            success=True,
            found=bool(result.get("found")),
            bound=bool(result.get("bound")),
            email=used_by_email,
            code_status=result.get("status"),
            code_status_label=_get_code_status_label(result.get("status")),
            used_at=result.get("used_at"),
            message=result.get("message"),
            error=None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"前台查询绑定邮箱失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询绑定邮箱失败: {str(e)}"
        )


@router.post("/bound-email/withdraw", response_model=BoundEmailWithdrawResponse)
async def withdraw_bound_email(
    request: BoundEmailWithdrawRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    前台自助撤销已关闭，仅保留接口级拦截，避免旧页面或脚本继续调用。
    """
    code = (request.code or "").strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="兑换码不能为空"
        )

    logger.info("前台自助撤销已关闭，拒绝撤销兑换码绑定邮箱: %s", code)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=FRONT_WITHDRAW_DISABLED_MESSAGE
    )


@router.post("/confirm", response_model=RedeemResponse)
async def confirm_redeem(
    request: RedeemRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    确认兑换并加入 Team

    Args:
        request: 兑换请求
        db: 数据库会话

    Returns:
        兑换结果
    """
    try:
        logger.info(f"兑换请求: {request.email} -> Team {request.team_id} (兑换码: {request.code})")

        result = await invite_queue_service.submit_redeem_job(
            db_session=db,
            email=request.email,
            code=request.code,
        )

        if not result["success"]:
            # 根据错误类型返回不同的状态码
            error_msg = result.get("error") or "未知原因"
            if any(kw in error_msg for kw in ["不存在", "已使用", "已过期", "截止时间", "已满", "席位", "质保", "无效", "失效", "处理中", "正在被其他邮箱处理", "maximum number of seats", "绑定的 Team", "固定 Team"]):
                status_code = status.HTTP_400_BAD_REQUEST
                if any(kw in error_msg for kw in ["已满", "席位", "maximum number of seats"]):
                    status_code = status.HTTP_409_CONFLICT
                raise HTTPException(
                    status_code=status_code,
                    detail=error_msg
                )
            else:
                # 默认系统内部错误
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=error_msg
                )

        return RedeemResponse(
            success=result.get("success", False),
            queued=result.get("queued", False),
            job_id=result.get("job_id"),
            job_status=result.get("job_status"),
            poll_after_ms=result.get("poll_after_ms"),
            message=result.get("message"),
            team_info=result.get("team_info"),
            error=result.get("error")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"兑换失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"兑换失败: {str(e)}"
        )
