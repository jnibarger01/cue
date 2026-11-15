import os
import unittest
from unittest.mock import patch

os.environ["CUE_WORKER_TOKEN"] = "test-worker-token-0123456789abcdef"

import worker


class PrivateWorkerTests(unittest.TestCase):
    def setUp(self):
        worker.app.config.update(TESTING=True)
        self.client = worker.app.test_client()

    def test_worker_rejects_requests_without_a_service_token(self):
        with patch.dict(os.environ, {"CUE_WORKER_TOKEN": ""}):
            response = self.client.post("/", json={"urls": ["https://youtu.be/abcdefghijk"]})
        self.assertEqual(response.status_code, 503)

    def test_worker_rejects_invalid_service_tokens(self):
        response = self.client.post(
            "/",
            json={"urls": ["https://youtu.be/abcdefghijk"]},
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(response.status_code, 401)

    def test_worker_rejects_invalid_payloads(self):
        response = self.client.post(
            "/",
            json={"urls": []},
            headers={"Authorization": "Bearer test-worker-token-0123456789abcdef"},
        )
        self.assertEqual(response.status_code, 400)

    def test_worker_returns_transcripts_only_with_valid_service_token(self):
        with patch.object(worker, "lookup", return_value={"video_id": "abcdefghijk", "text": "caption"}):
            response = self.client.post(
                "/",
                json={"urls": ["https://youtu.be/abcdefghijk"]},
                headers={"Authorization": "Bearer test-worker-token-0123456789abcdef"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["text"], "caption")


if __name__ == "__main__":
    unittest.main()
