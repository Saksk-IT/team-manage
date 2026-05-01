import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.routes.user import redeem_page


class UserRedeemTransitionOverlayTests(unittest.IsolatedAsyncioTestCase):
    def _build_request(self) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    async def test_redeem_page_includes_transition_overlay_shell(self):
        request = self._build_request()
        db = AsyncMock()

        with patch(
            "app.services.settings.settings_service.get_front_announcement_config",
            new=AsyncMock(return_value={"enabled": False, "content": ""})
        ), patch(
            "app.services.settings.settings_service.get_customer_service_config",
            new=AsyncMock(return_value={
                "enabled": False,
                "qr_code_url": "",
                "link_url": "",
                "link_text": "",
                "text_content": ""
            })
        ), patch(
            "app.services.settings.settings_service.get_purchase_link_config",
            new=AsyncMock(return_value={
                "enabled": False,
                "url": "",
                "button_text": ""
            })
        ), patch(
            "app.services.settings.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_warranty_fake_success_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.settings.settings_service.get_warranty_email_check_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.settings.settings_service.get_number_pool_config",
            new=AsyncMock(return_value={"enabled": False})
        ), patch(
            "app.services.team.TeamService.get_total_available_seats",
            new=AsyncMock(return_value=12)
        ):
            response = await redeem_page(request=request, db=db)

        html = response.body.decode("utf-8")

        self.assertIn('id="requestTransitionOverlay"', html)
        self.assertIn('id="transitionOverlayTitle"', html)
        self.assertIn('id="transitionOverlayMessage"', html)
        self.assertIn('id="transitionOverlayTimeline"', html)
        self.assertIn('id="transitionOverlayHint"', html)

    def test_redeem_js_defines_waiting_flow_configs(self):
        script = Path("app/static/js/redeem.js").read_text(encoding="utf-8")

        self.assertIn("const REDEEM_LOADING_FLOW =", script)
        self.assertIn("const WARRANTY_STATUS_LOADING_FLOW =", script)
        self.assertIn("const WARRANTY_ORDER_REFRESH_LOADING_FLOW =", script)
        self.assertIn("const WARRANTY_CLAIM_LOADING_FLOW =", script)
        self.assertIn("const customerServicePromptModal =", script)
        self.assertIn("function setCustomerServicePromptOpen(isOpen)", script)
        self.assertIn("const warrantyEmailCheckEnabled =", script)
        self.assertIn("function renderWarrantyEmailCheckResult(data, email)", script)
        self.assertIn("warrantyCheckParams.set('user_id', sub2apiUserId)", script)
        self.assertIn("function showCustomerServiceQrReminder()", script)
        self.assertEqual(script.count("showCustomerServiceQrReminder();"), 3)
        self.assertIn("openTransitionOverlay(", script)
        self.assertIn("advanceTransitionOverlay(", script)
        self.assertIn("closeTransitionOverlay()", script)

    def test_redeem_js_renders_multi_warranty_order_submission(self):
        script = Path("app/static/js/redeem.js").read_text(encoding="utf-8")

        self.assertIn("data?.warranty_orders", script)
        self.assertIn("warranty-order-refresh-btn", script)
        self.assertIn("warranty-order-claim-btn", script)
        self.assertIn("data-entry-id", script)
        self.assertIn("return `entry:${entryId}`;", script)
        self.assertIn(": (existingOrders.length > 0 ? existingOrders : [order]);", script)
        self.assertIn("refreshWarrantyOrderStatus(email, button.dataset.code || null, button, button.dataset.entryId || null)", script)
        self.assertIn("submitWarrantyClaim(email, button.dataset.code || null, button, button.dataset.entryId || null)", script)
        self.assertIn("...(code ? { code } : {})", script)
        self.assertIn("...(entryId ? { entry_id: Number(entryId) } : {})", script)

    def test_redeem_js_normalizes_non_banned_warranty_order_status(self):
        script = Path("app/static/js/redeem.js").read_text(encoding="utf-8")

        self.assertIn("return { label: '可用', className: 'status-badge--success' };", script)
        self.assertIn("normalizeWarrantyStatusMessage", script)
        self.assertIn("${escapeHtml(badge.label)}</span>", script)
        self.assertNotIn("latestTeam.status_label || badge.label", script)


if __name__ == "__main__":
    unittest.main()
