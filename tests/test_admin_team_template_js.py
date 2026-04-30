import unittest
from types import SimpleNamespace

from app.main import templates


class AdminTeamTemplateJsTests(unittest.TestCase):
    def _render_admin_index(self, active_page="dashboard", team_mode="standard"):
        team = SimpleNamespace(
            id=1,
            email="owner@example.com",
            account_id="acc-1",
            team_name="Team 1",
            current_members=1,
            max_members=5,
            subscription_plan="chatgptteamplan",
            expires_at=None,
            device_code_auth_enabled=False,
            status="active",
            warranty_unavailable=False,
            warranty_unavailable_reason=None,
            warranty_unavailable_at=None,
            import_status="classified",
            import_tag_label="",
            imported_by_username="",
            created_at=None,
            import_decision_label="",
            account_role="account-owner",
            access_token="",
            refresh_token="",
            session_token="",
            client_id="",
        )
        request = SimpleNamespace(
            url=SimpleNamespace(path="/admin/number-pool" if active_page == "number_pool" else "/admin")
        )

        return templates.env.get_template("admin/index.html").render(
            request=request,
            user={"username": "admin", "is_super_admin": True},
            active_page=active_page,
            page_title="号池" if active_page == "number_pool" else "控制台",
            team_mode=team_mode,
            is_pending_mode=False,
            is_review_mode=False,
            teams=[team],
            stats={"total_teams": 1, "available_teams": 1, "total_seats": 4, "remaining_seats": 3},
            search="",
            status_filter="",
            review_status_filter="",
            import_tag_filter="",
            imported_by_user_id_filter="",
            imported_from_filter="",
            imported_to_filter="",
            expires_from_filter="",
            expires_to_filter="",
            device_auth_filter="",
            members_min_filter="",
            members_max_filter="",
            import_tag_options=[],
            importer_options=[],
            team_auto_refresh_enabled=False,
            team_auto_refresh_interval_minutes=5,
            pagination={"current_page": 1, "total_pages": 1, "total": 1, "per_page": 100},
            number_pool_enabled=True,
        )

    def test_dashboard_batch_transfer_target_type_is_not_html_escaped(self):
        html = self._render_admin_index()

        self.assertIn('const targetType = "number_pool";', html)
        self.assertNotIn('const targetType = &#34;number_pool&#34;;', html)
        self.assertIn('批量转入号池', html)

    def test_number_pool_batch_transfer_target_type_is_not_html_escaped(self):
        html = self._render_admin_index(active_page="number_pool", team_mode="number_pool")

        self.assertIn('const targetType = "standard";', html)
        self.assertNotIn('const targetType = &#34;standard&#34;;', html)
        self.assertIn('批量转回控制台', html)


if __name__ == "__main__":
    unittest.main()
