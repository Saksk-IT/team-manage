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
            "app.services.settings.settings_service.get_warranty_service_config",
            new=AsyncMock(return_value={"enabled": True})
        ), patch(
            "app.services.settings.settings_service.get_warranty_fake_success_config",
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
        self.assertIn('id="previewTransitionRedeemBtn"', html)
        self.assertIn('id="previewTransitionWarrantyStatusBtn"', html)
        self.assertIn('id="previewTransitionWarrantyClaimBtn"', html)
        self.assertIn("动效预览入口", html)

    def test_redeem_js_defines_three_waiting_flow_configs(self):
        script = Path("app/static/js/redeem.js").read_text(encoding="utf-8")

        self.assertIn("const REDEEM_LOADING_FLOW =", script)
        self.assertIn("const WARRANTY_STATUS_LOADING_FLOW =", script)
        self.assertIn("const WARRANTY_CLAIM_LOADING_FLOW =", script)
        self.assertIn("const TRANSITION_PREVIEW_MAP =", script)
        self.assertIn("openTransitionOverlay(", script)
        self.assertIn("advanceTransitionOverlay(", script)
        self.assertIn("closeTransitionOverlay()", script)
        self.assertIn("previewTransitionFlow(", script)


if __name__ == "__main__":
    unittest.main()
