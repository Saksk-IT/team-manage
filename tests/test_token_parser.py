import json
import unittest

from app.utils.token_parser import TokenParser


class TokenParserJsonImportTests(unittest.TestCase):
    def setUp(self):
        self.parser = TokenParser()

    def test_extracts_team_info_from_full_json_object(self):
        payload = {
            "user": {
                "email": "team-owner@example.com"
            },
            "account": {
                "id": "12345678-1234-1234-1234-1234567890ab"
            },
            "accessToken": "eyJaccess.payload.signature",
            "sessionToken": "eyJsession.payload.signature",
            "clientId": "app_ABC123"
        }

        result = self.parser.parse_team_import_text(json.dumps(payload, indent=2))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["token"], "eyJaccess.payload.signature")
        self.assertEqual(result[0]["session_token"], "eyJsession.payload.signature")
        self.assertEqual(result[0]["email"], "team-owner@example.com")
        self.assertEqual(result[0]["account_id"], "12345678-1234-1234-1234-1234567890ab")
        self.assertEqual(result[0]["client_id"], "app_ABC123")

    def test_extracts_multiple_teams_from_json_array_and_concatenated_json(self):
        payloads = [
            {
                "user": {"email": "one@example.com"},
                "account": {"id": "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"},
                "accessToken": "eyJone.payload.signature"
            },
            {
                "user": {"email": "two@example.com"},
                "account": {"id": "cccccccc-4444-5555-6666-dddddddddddd"},
                "accessToken": "eyJtwo.payload.signature",
                "refreshToken": "rt-test.token"
            }
        ]

        array_result = self.parser.parse_team_import_text(json.dumps(payloads))
        joined_result = self.parser.parse_team_import_text(
            "\n".join(json.dumps(item) for item in payloads)
        )

        self.assertEqual(len(array_result), 2)
        self.assertEqual([item["email"] for item in array_result], ["one@example.com", "two@example.com"])
        self.assertEqual(len(joined_result), 2)
        self.assertEqual([item["token"] for item in joined_result], [
            "eyJone.payload.signature",
            "eyJtwo.payload.signature"
        ])
        self.assertEqual(joined_result[1]["refresh_token"], "rt-test.token")


if __name__ == "__main__":
    unittest.main()
