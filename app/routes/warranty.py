"""
质保相关路由
处理用户质保查询请求
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.invite_queue import invite_queue_service
from app.services.settings import settings_service
from app.services.warranty import warranty_service
from app.utils.rich_text import rich_text_to_plain_text

TEAM_AVAILABLE_NO_WARRANTY_MESSAGE = "您所在的Team可以正常使用，无需提交质保"
WARRANTY_EMAIL_MISSING_REDEEM_CODE_MESSAGE = "请加入 QQ 群，联系群主处理。"
WARRANTY_EMAIL_WRONG_REDEEM_CODE_MESSAGE = "您的质保兑换码错误"


def _parse_optional_positive_int(value) -> Optional[int]:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


router = APIRouter(
    prefix="/warranty",
    tags=["warranty"]
)


async def ensure_warranty_service_enabled(db_session: AsyncSession) -> None:
    config = await settings_service.get_warranty_service_config(db_session)
    if not config.get("enabled"):
        raise HTTPException(status_code=404, detail="前台质保服务未开启")


async def ensure_warranty_order_flow_enabled(db_session: AsyncSession) -> None:
    await ensure_warranty_service_enabled(db_session)
    email_check_config = await settings_service.get_warranty_email_check_config(db_session)
    if email_check_config.get("enabled"):
        raise HTTPException(status_code=400, detail="当前已启用质保邮箱名单判定模式，订单查询与质保提交已关闭")


class WarrantyCheckRequest(BaseModel):
    """质保查询请求"""
    email: EmailStr
    warranty_code: Optional[str] = Field(None, max_length=128, description="质保兑换码")


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
    mode: str = "orders"
    matched: Optional[bool] = None
    content_html: Optional[str] = None
    template_key: Optional[str] = None
    generated_redeem_code: Optional[str] = None
    generated_redeem_code_remaining_days: Optional[int] = None
    generated_redeem_code_reused: Optional[bool] = None
    generated_redeem_code_error: Optional[str] = None
    skip_redeem_code_generation: bool = False
    missing_redeem_code: bool = False
    wrong_redeem_code: bool = False
    super_code_matched: bool = False
    usable_linked_team: Optional[dict] = None
    latest_team: Optional[WarrantyLatestTeamInfo] = None
    warranty_info: Optional[dict] = None
    warranty_orders: List[dict] = Field(default_factory=list)
    message: Optional[str]
    error: Optional[str]


class WarrantyOrderStatusRequest(BaseModel):
    """单个质保订单 Team 状态刷新请求"""
    email: EmailStr
    code: Optional[str] = None
    entry_id: int = Field(..., gt=0)


@router.post("/check", response_model=WarrantyCheckResponse)
async def check_warranty(
    request: WarrantyCheckRequest = Body(...),
    http_request: Request = None,
    db_session: AsyncSession = Depends(get_db)
):
    """
    查询质保邮箱状态；名单判定模式开启时校验邮箱与质保兑换码是否匹配。
    """
    await ensure_warranty_service_enabled(db_session)
    email_check_config = await settings_service.get_warranty_email_check_config(db_session)
    if email_check_config.get("enabled"):
        result = await warranty_service.check_warranty_email_membership(
            db_session=db_session,
            email=request.email,
            warranty_code=request.warranty_code,
            match_templates=email_check_config.get("match_templates", []),
            miss_templates=email_check_config.get("miss_templates", []),
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error") or "状态查询失败")

        template_matched = bool(result.get("template_matched", result.get("matched")))
        templates = (
            email_check_config.get("match_templates", [])
            if template_matched
            else email_check_config.get("miss_templates", [])
        )
        fallback_content = (
            email_check_config.get("match_content")
            if template_matched
            else email_check_config.get("miss_content")
        ) or ""
        content_html = (
            settings_service.get_warranty_email_check_template_content(
                templates,
                result.get("template_key"),
            )
            or fallback_content
        )

        generated_code = None
        generated_code_remaining_days = None
        generated_code_reused = None
        generated_code_error = None
        user_id = _parse_optional_positive_int(http_request.query_params.get("user_id") if http_request else None)
        should_skip_redeem_code = bool(result.get("skip_redeem_code_generation"))
        if should_skip_redeem_code:
            skip_message = result.get("message") or (
                WARRANTY_EMAIL_WRONG_REDEEM_CODE_MESSAGE
                if result.get("wrong_redeem_code")
                else (
                    WARRANTY_EMAIL_MISSING_REDEEM_CODE_MESSAGE
                    if result.get("missing_redeem_code")
                    else TEAM_AVAILABLE_NO_WARRANTY_MESSAGE
                )
            )
            content_html = f"<p>{skip_message}</p>"

        if bool(result.get("matched")) and not should_skip_redeem_code:
            if result.get("generated_redeem_code"):
                generated_code = result.get("generated_redeem_code")
                generated_code_remaining_days = result.get("generated_redeem_code_remaining_days")
                generated_code_reused = True
            else:
                code_result = await warranty_service.ensure_warranty_email_check_redeem_code(
                    db_session=db_session,
                    email=request.email,
                    user_id=user_id,
                    template_lock=result.get("template_lock"),
                    warranty_entry=result.get("selected_entry"),
                )
                if code_result.get("success"):
                    generated_code = code_result.get("code")
                    generated_code_remaining_days = code_result.get("remaining_days")
                    generated_code_reused = bool(code_result.get("reused"))
                else:
                    generated_code_error = code_result.get("error") or "兑换码生成失败"

        message = rich_text_to_plain_text(content_html)

        return {
            "success": True,
            "can_claim": False,
            "mode": "email_check",
            "matched": bool(result.get("matched")),
            "content_html": content_html,
            "template_key": result.get("template_key"),
            "generated_redeem_code": generated_code,
            "generated_redeem_code_remaining_days": generated_code_remaining_days,
            "generated_redeem_code_reused": generated_code_reused,
            "generated_redeem_code_error": generated_code_error,
            "skip_redeem_code_generation": should_skip_redeem_code,
            "missing_redeem_code": bool(result.get("missing_redeem_code")),
            "wrong_redeem_code": bool(result.get("wrong_redeem_code")),
            "super_code_matched": bool(result.get("super_code_matched")),
            "usable_linked_team": result.get("usable_linked_team"),
            "latest_team": None,
            "warranty_info": None,
            "warranty_orders": [],
            "message": message,
            "error": None,
        }

    result = await warranty_service.get_warranty_claim_status(
        db_session=db_session,
        email=request.email
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "状态查询失败")

    return {
        "success": True,
        "can_claim": result.get("can_claim", False),
        "mode": "orders",
        "matched": None,
        "content_html": None,
        "latest_team": result.get("latest_team"),
        "warranty_info": result.get("warranty_info"),
        "warranty_orders": result.get("warranty_orders", []),
        "message": result.get("message"),
        "error": None,
    }


@router.post("/order-status")
async def refresh_warranty_order_status(
    request: WarrantyOrderStatusRequest,
    db_session: AsyncSession = Depends(get_db)
):
    """
    按质保订单独立刷新其对应邮箱上次加入的 Team 状态。
    """
    await ensure_warranty_order_flow_enabled(db_session)
    result = await warranty_service.refresh_warranty_order_status(
        db_session=db_session,
        email=request.email,
        entry_id=request.entry_id,
        code=request.code,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "订单状态刷新失败")

    return result


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
    await ensure_warranty_order_flow_enabled(db_session)
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
    await ensure_warranty_order_flow_enabled(db_session)
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
    前台质保模拟成功模式下的提交资格校验。
    """
    await ensure_warranty_order_flow_enabled(db_session)
    config = await settings_service.get_warranty_fake_success_config(db_session)
    if not config.get("enabled"):
        raise HTTPException(status_code=400, detail="前台质保模拟成功模式未启用")

    result = await warranty_service.validate_warranty_claim_input(
        db_session=db_session,
        email=request.email,
        require_latest_team_banned=True,
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
    await ensure_warranty_order_flow_enabled(db_session)
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
