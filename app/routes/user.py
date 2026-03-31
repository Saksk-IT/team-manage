"""
用户路由
处理用户兑换页面
"""
import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    tags=["user"]
)


@router.get("/", response_class=HTMLResponse)
async def redeem_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    用户兑换页面

    Args:
        request: FastAPI Request 对象
        db: 数据库会话

    Returns:
        用户兑换页面 HTML
    """
    try:
        from app.main import templates
        from app.services.team import TeamService
        from app.services.settings import settings_service

        warranty_service_config = await settings_service.get_warranty_service_config(db)
        warranty_fake_success_config = await settings_service.get_warranty_fake_success_config(db)
        warranty_service_enabled = warranty_service_config["enabled"]
        warranty_fake_success_enabled = warranty_service_enabled and warranty_fake_success_config["enabled"]

        if warranty_fake_success_enabled:
            remaining_spots = await settings_service.get_warranty_fake_success_remaining_spots(db)
        else:
            team_service = TeamService()
            remaining_spots = await team_service.get_total_available_seats(db)

        logger.info(f"用户访问兑换页面，剩余车位: {remaining_spots}")

        return templates.TemplateResponse(
            request,
            "user/redeem.html",
            {
                "request": request,
                "remaining_spots": remaining_spots,
                "warranty_service_enabled": warranty_service_enabled,
                "warranty_fake_success_enabled": warranty_fake_success_enabled
            }
        )

    except Exception as e:
        logger.error(f"渲染兑换页面失败: {e}")
        return HTMLResponse(
            content=f"<h1>页面加载失败</h1><p>{str(e)}</p>",
            status_code=500
        )
