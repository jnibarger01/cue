import os
import re
import unittest
from unittest.mock import Mock, patch

from security import hash_password

os.environ.update({
    "CUE_USERNAME": "jace",
    "CUE_PASSWORD_HASH": hash_password("a sufficiently long test password"),
    "CUE_SESSION_SECRET": "test-session-secret-not-for-production",
    "CUE_WORKER_URL": "http://127.0.0.1:8787/cue-worker",
    "CUE_WORKER_TOKEN": "test-worker-token-0123456789abcdef",
    "CUE_WORKER_ALLOW_HTTP": "true",
    "CUE_COOKIE_SECURE": "false",
})

import app as cue_app


class CueAuthenticationTests(unittest.TestCase):
    def setUp(self):
        cue_app.app.config.update(
            TESTING=True,
            SECRET_KEY=os.environ["CUE_SESSION_SECRET"],
            SESSION_COOKIE_SECURE=False,
        )
        cue_app._login_attempts.clear()
        self.client = cue_app.app.test_client()

    def login(self, password="a sufficiently long test password"):
        response = self.client.get("/login")
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match, response.data.decode())
        return self.client.post(
            "/login",
            data={
                "csrf_token": match.group(1).decode(),
                "username": "jace",
                "password": password,
            },
            follow_redirects=True,
        )

    def test_home_redirects_to_login_when_not_authenticated(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_transcript_api_rejects_anonymous_requests(self):
        response = self.client.post("/api/transcripts", json={"urls": ["https://youtu.be/abcdefghijk"]})
        self.assertEqual(response.status_code, 401)

    def test_login_rejects_invalid_password(self):
        response = self.login("incorrect password")
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Invalid username or password", response.data)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_valid_login_opens_the_private_app(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"YouTube transcripts.", response.data)
        self.assertIn(b"/logout", response.data)

    def test_authenticated_api_requires_csrf_header(self):
        self.login()
        response = self.client.post("/api/transcripts", json={"urls": ["https://youtu.be/abcdefghijk"]})
        self.assertEqual(response.status_code, 400)

    def test_authenticated_api_forwards_to_private_worker(self):
        self.login()
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        upstream = Mock()
        upstream.status_code = 200
        upstream.json.return_value = {"results": [{"video_id": "abcdefghijk", "text": "caption"}]}
        with patch.object(cue_app.requests, "post", return_value=upstream) as post:
            response = self.client.post(
                "/api/transcripts",
                json={"urls": ["https://youtu.be/abcdefghijk"]},
                headers={"X-CSRF-Token": csrf_token},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["text"], "caption")
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:8787/cue-worker")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-worker-token-0123456789abcdef")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_authenticated_api_fails_closed_without_worker_configuration(self):
        self.login()
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        with patch.dict(os.environ, {"CUE_WORKER_URL": "", "CUE_WORKER_TOKEN": ""}):
            response = self.client.post(
                "/api/transcripts",
                json={"urls": ["https://youtu.be/abcdefghijk"]},
                headers={"X-CSRF-Token": csrf_token},
            )
        self.assertEqual(response.status_code, 503)

    def test_app_fails_closed_when_login_secrets_are_missing(self):
        with patch.dict(os.environ, {"CUE_USERNAME": "", "CUE_PASSWORD_HASH": "", "CUE_SESSION_SECRET": ""}):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"not configured", response.data.lower())


if __name__ == "__main__":
    unittest.main()
