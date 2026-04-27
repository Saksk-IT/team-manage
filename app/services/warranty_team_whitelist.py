"""兼容旧导入路径：邮箱白名单服务已升级为全局自动清理依赖。"""

from app.services.email_whitelist import EmailWhitelistService, email_whitelist_service

WarrantyTeamWhitelistService = EmailWhitelistService
warranty_team_whitelist_service = email_whitelist_service
