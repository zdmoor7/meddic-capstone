import json
import os
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import app as app_module  # noqa: E402
from tests.test_meddic import element, reply  # noqa: E402


class NotesCleanupRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def post_notes(self, model_reply):
        with mock.patch.object(app_module.client, "send_message", return_value=model_reply):
            return self.client.post("/notes-cleanup", json={"notes": "some notes"})

    def test_returns_meddic_and_gate(self):
        res = self.post_notes(reply({"Metrics": element("", "RED", ["What is the target?"])}))
        self.assertEqual(res.status_code, 200)
        body = res.get_json()["result"]
        self.assertEqual(body["meddic"]["Metrics"]["status"], "RED")
        self.assertFalse(body["gate"]["ready"])

    def test_elements_keep_framework_order(self):
        res = self.post_notes(reply())
        keys = list(json.loads(res.get_data(as_text=True))["result"]["meddic"])
        self.assertEqual(keys[0], "Metrics")
        self.assertEqual(keys[-1], "Champion")

    def test_malformed_model_output_is_502(self):
        res = self.post_notes("I could not produce JSON for this.")
        self.assertEqual(res.status_code, 502)
        self.assertIn("couldn't read", res.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
