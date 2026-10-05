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



class PrescriptionRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        meddic = json.loads(reply())["meddic"]
        self.payload = {"meddic_output": json.dumps(meddic), "buyer": "Northgate SaaS",
                        "call_balance": {"measured": True, "pitching_pct": 10}, "gate_overridden": True}

    def post(self, model_reply):
        with mock.patch.object(app_module.client, "send_message", return_value=model_reply), \
             mock.patch.object(app_module, "retrieve_relevant_chunks", return_value=["doc chunk"]), \
             mock.patch.object(app_module.store, "save_deal", return_value=1) as save:
            res = self.client.post("/get-prescription", json=self.payload)
        return res, save

    def test_returns_agenda_keyed_prescription(self):
        from tests.test_prescription import AGENDA, reply as prescription_reply
        res, save = self.post(prescription_reply())
        self.assertEqual(res.status_code, 200)
        body = res.get_json()["result"]
        self.assertEqual(body["demo_agenda"], AGENDA)
        self.assertEqual([s["step"] for s in body["demo_prescription"]], AGENDA)
        self.assertEqual(res.get_json()["deal_id"], 1)
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


class RefineRouteTests(unittest.TestCase):
    def setUp(self):
        from tests.test_prescription import reply as prescription_reply
        self.client = app_module.app.test_client()
        self.plan = app_module.parse_prescription_response(prescription_reply())
        self.meddic = json.loads(reply())["meddic"]

    def test_refine_returns_merged_plan(self):
        model = json.dumps({"reply": "Done.", "changes": {"changed_steps": [
            {"step": "Connect HubSpot live", "points": ["New point."]}]}})
        with mock.patch.object(app_module.client, "send_message", return_value=model) as send:
            res = self.client.post("/refine", json={"meddic": self.meddic, "call_balance": None, "prescription": self.plan,
                                                     "messages": [{"role": "user", "content": "Tighten step 2"}]})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()["result"]
        self.assertEqual(body["changed_steps"], ["Connect HubSpot live"])
        self.assertEqual(body["prescription"]["demo_prescription"][1]["points"], ["New point."])
        self.assertEqual(send.call_args.kwargs["messages"], [{"role": "user", "content": "Tighten step 2"}])

    def test_refine_rejects_bad_input(self):
        res = self.client.post("/refine", json={"prescription": self.plan, "messages": []})
        self.assertEqual(res.status_code, 400)

    def test_ready_check_saves_and_reviews(self):
        review = json.dumps({"gaps": [{"severity": "risk", "area": "Show ROI dashboard", "issue": "Vague.", "fix": "Use numbers."}]})
        with mock.patch.object(app_module.client, "send_message", return_value=review), \
             mock.patch.object(app_module.store, "update_prescription", return_value=True) as update:
            res = self.client.post("/ready-check", json={"deal_id": 3, "meddic": self.meddic, "prescription": self.plan})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["saved"])
        self.assertTrue(res.get_json()["result"]["ready"])
        self.assertEqual(update.call_args[0][0], 3)

    def test_ready_check_survives_review_failure(self):
        with mock.patch.object(app_module.client, "send_message", side_effect=RuntimeError("timeout")):
            res = self.client.post("/ready-check", json={"meddic": self.meddic, "prescription": self.plan})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.get_json()["saved"])
        self.assertTrue(res.get_json()["result"]["warnings"])


if __name__ == "__main__":
    unittest.main()
