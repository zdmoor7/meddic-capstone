import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
# Keep test deals out of the real insights.db.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["STORAGE_BACKEND"] = "sqlite"

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


class PrescriptionRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        meddic = json.loads(reply())["meddic"]
        self.payload = {"meddic_output": json.dumps(meddic), "buyer": "Northgate SaaS",
                        "call_balance": {"measured": True, "pitching_pct": 10}, "gate_overridden": True}

    def post(self, model_reply):
        with mock.patch.object(app_module.client, "send_message", return_value=model_reply), \
             mock.patch.object(app_module, "retrieve_relevant_chunks", return_value=["doc chunk"]), \
             mock.patch.object(app_module.store, "save_deal") as save:
            res = self.client.post("/get-prescription", json=self.payload)
        return res, save

    def test_returns_agenda_keyed_prescription(self):
        from tests.test_prescription import AGENDA, reply as prescription_reply
        res, save = self.post(prescription_reply())
        self.assertEqual(res.status_code, 200)
        body = res.get_json()["result"]
        self.assertEqual(body["demo_agenda"], AGENDA)
        self.assertEqual([s["step"] for s in body["demo_prescription"]], AGENDA)
        save.assert_called_once()
        deal = save.call_args[0][0]
        self.assertEqual(deal["buyer"], "Northgate SaaS")
        self.assertTrue(deal["gate_overridden"])
        self.assertEqual(deal["call_balance"]["pitching_pct"], 10)
        self.assertEqual(deal["prescription"]["demo_agenda"], AGENDA)

    def test_malformed_prescription_is_502(self):
        res, save = self.post('{"deal_overview": "x", "demo_prescription": "just prose"}')
        self.assertEqual(res.status_code, 502)
        save.assert_not_called()
