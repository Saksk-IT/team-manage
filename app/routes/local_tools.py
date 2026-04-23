"""
独立本地工具页
数据仅保存在浏览器本地
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["local_tools"])


@router.get("/local-tools", response_class=HTMLResponse)
async def local_tools_page(request: Request):
    from app.main import templates

    return templates.TemplateResponse(
        request,
        "tools/local_tools.html",
        {
            "request": request,
        }
    )
