"""
管理后台侧边栏菜单定义与排序工具。
"""
from dataclasses import asdict, dataclass
from collections.abc import Sequence


@dataclass(frozen=True)
class AdminSidebarItem:
    id: str
    active_page: str
    href: str
    icon: str
    label: str


SUPER_ADMIN_SIDEBAR_ITEMS: tuple[AdminSidebarItem, ...] = (
    AdminSidebarItem("dashboard", "dashboard", "/admin", "layout-dashboard", "控制台"),
    AdminSidebarItem("pending_teams", "pending_teams", "/admin/pending-teams", "inbox", "导入记录"),
    AdminSidebarItem("sub_admins", "sub_admins", "/admin/sub-admins", "user-cog", "子管理员"),
    AdminSidebarItem("email_whitelist", "email_whitelist", "/admin/email-whitelist", "shield-check", "邮箱白名单"),
    AdminSidebarItem("warranty_emails", "warranty_emails", "/admin/warranty-emails", "key-round", "质保邮箱列表"),
    AdminSidebarItem(
        "warranty_claim_records",
        "warranty_claim_records",
        "/admin/warranty-claim-records",
        "clipboard-list",
        "质保提交记录",
    ),
    AdminSidebarItem("codes", "codes", "/admin/codes", "ticket", "兑换码管理"),
    AdminSidebarItem("number_pool", "number_pool", "/admin/number-pool", "layers", "号池"),
    AdminSidebarItem("records", "records", "/admin/records", "file-text", "使用记录"),
    AdminSidebarItem(
        "team_member_snapshots",
        "team_member_snapshots",
        "/admin/team-member-snapshots",
        "users-round",
        "成员快照",
    ),
    AdminSidebarItem(
        "team_refresh_records",
        "team_refresh_records",
        "/admin/team-refresh-records",
        "refresh-cw",
        "Team 刷新记录",
    ),
    AdminSidebarItem(
        "team_cleanup_records",
        "team_cleanup_records",
        "/admin/team-cleanup-records",
        "broom",
        "自动清理记录",
    ),
    AdminSidebarItem("front_page", "front_page", "/admin/front-page", "store", "前台页面"),
    AdminSidebarItem("settings", "settings", "/admin/settings", "settings", "系统设置"),
)

IMPORT_ADMIN_SIDEBAR_ITEMS: tuple[AdminSidebarItem, ...] = (
    AdminSidebarItem("import_only", "import_only", "/admin/import-only", "upload-cloud", "导入 Team / 我的导入"),
)

SUPER_ADMIN_SIDEBAR_ITEM_MAP = {item.id: item for item in SUPER_ADMIN_SIDEBAR_ITEMS}


def _serialize_item(item: AdminSidebarItem) -> dict[str, str]:
    return asdict(item)


def _is_super_admin_user(user: dict | None) -> bool:
    return bool(user and user.get("is_super_admin", user.get("username") == "admin"))


def get_default_admin_sidebar_order() -> list[str]:
    return [item.id for item in SUPER_ADMIN_SIDEBAR_ITEMS]


def normalize_admin_sidebar_order(order: Sequence[str] | None) -> list[str]:
    if order is None or isinstance(order, (str, bytes)) or not isinstance(order, Sequence):
        raise ValueError("侧边栏排序不能为空")

    normalized_order: list[str] = []
    invalid_ids: list[str] = []
    allowed_ids = set(SUPER_ADMIN_SIDEBAR_ITEM_MAP)

    for raw_menu_id in order:
        menu_id = str(raw_menu_id or "").strip()
        if not menu_id:
            continue
        if menu_id not in allowed_ids:
            invalid_ids.append(menu_id)
            continue
        if menu_id not in normalized_order:
            normalized_order.append(menu_id)

    if invalid_ids:
        raise ValueError(f"包含无效菜单项: {', '.join(invalid_ids)}")
    if not normalized_order:
        raise ValueError("侧边栏排序不能为空")

    return normalized_order + [
        menu_id
        for menu_id in get_default_admin_sidebar_order()
        if menu_id not in normalized_order
    ]


def safe_normalize_admin_sidebar_order(order: Sequence[str] | None) -> list[str]:
    try:
        return normalize_admin_sidebar_order(order)
    except ValueError:
        return get_default_admin_sidebar_order()


def get_admin_sidebar_items(
    order: Sequence[str] | None = None,
    *,
    number_pool_enabled: bool = True,
) -> list[dict[str, str]]:
    normalized_order = safe_normalize_admin_sidebar_order(order) if order is not None else get_default_admin_sidebar_order()
    return [
        _serialize_item(SUPER_ADMIN_SIDEBAR_ITEM_MAP[menu_id])
        for menu_id in normalized_order
        if menu_id in SUPER_ADMIN_SIDEBAR_ITEM_MAP
        and (number_pool_enabled or menu_id != "number_pool")
    ]


def get_admin_sidebar_items_for_user(
    user: dict | None,
    order: Sequence[str] | None = None,
    *,
    number_pool_enabled: bool = True,
) -> list[dict[str, str]]:
    if _is_super_admin_user(user):
        return get_admin_sidebar_items(order, number_pool_enabled=number_pool_enabled)
    return [_serialize_item(item) for item in IMPORT_ADMIN_SIDEBAR_ITEMS]
