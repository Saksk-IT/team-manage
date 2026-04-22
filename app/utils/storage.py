"""
存储路径工具。
"""
from pathlib import Path
from typing import Optional

from app.config import BASE_DIR, settings

CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX = "/uploads/customer-service/"
LEGACY_CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX = "/static/uploads/customer-service/"


def get_database_file_path() -> Path:
    """
    获取 SQLite 数据库文件路径。
    """
    database_url = str(settings.database_url or "").strip().strip('"').strip("'")
    marker = ":///"

    if marker not in database_url:
        raise ValueError("当前仅支持基于文件路径的 SQLite 数据库地址")

    return Path(database_url.split(marker, 1)[1])


def get_uploads_root_dir() -> Path:
    """
    获取持久化上传根目录。
    """
    return get_database_file_path().parent / "uploads"


def get_customer_service_upload_dir() -> Path:
    """
    获取客服二维码上传目录。
    """
    return get_uploads_root_dir() / "customer-service"


def get_legacy_customer_service_upload_dir() -> Path:
    """
    获取旧版客服二维码上传目录。
    """
    return BASE_DIR / "app" / "static" / "uploads" / "customer-service"


def build_customer_service_upload_url(filename: str) -> str:
    """
    构建客服二维码图片访问地址。
    """
    normalized_filename = _extract_filename(filename)
    if not normalized_filename:
        raise ValueError("无效的客服二维码文件名")

    return f"{CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX}{normalized_filename}"


def is_customer_service_upload_url(value: str) -> bool:
    """
    判断是否为站内客服二维码图片地址。
    """
    return bool(_extract_uploaded_filename((value or "").strip()))


def customer_service_upload_exists(value: str) -> bool:
    """
    判断站内客服二维码图片是否存在。
    """
    return bool(resolve_customer_service_upload_display_url(value))


def resolve_customer_service_upload_display_url(value: str) -> str:
    """
    返回可用的客服二维码图片地址；若文件不存在则返回空字符串。
    """
    normalized_value = (value or "").strip()
    filename = _extract_uploaded_filename(normalized_value)

    if not filename:
        return normalized_value

    persistent_path = get_customer_service_upload_dir() / filename
    if persistent_path.exists():
        return build_customer_service_upload_url(filename)

    if normalized_value.startswith(LEGACY_CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX):
        legacy_path = get_legacy_customer_service_upload_dir() / filename
        if legacy_path.exists():
            return normalized_value

    return ""


def _extract_uploaded_filename(value: str) -> Optional[str]:
    for prefix in (
        CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX,
        LEGACY_CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX,
    ):
        if value.startswith(prefix):
            return _extract_filename(value[len(prefix):])

    return None


def _extract_filename(value: str) -> Optional[str]:
    normalized_value = (value or "").strip()
    if not normalized_value:
        return None

    candidate = Path(normalized_value).name
    if candidate != normalized_value or candidate in {".", ".."}:
        return None

    return candidate
