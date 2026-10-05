import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from meddic import MEDDIC_ELEMENTS
from storage import get_store, to_crm_payload
from storage.crm_mock import CRMDealStore
from storage.sqlite_store import SQLiteDealStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_deal(metrics_status="GREEN", **extra):
    meddic = {name: {"content": "x", "flag": "", "status": "GREEN", "follow_up_questions": []}
              for name in MEDDIC_ELEMENTS}
    meddic["Metrics"] = {"content": "" if metrics_status == "RED" else "30 to 20 days", "flag": "",
                         "status": metrics_status, "follow_up_questions": ["What is the baseline?"]}
    deal = {
        "buyer": "Northgate SaaS",
        "created_at": "2026-10-05T10:00:00+00:00",
        "meddic": meddic,
        "call_balance": {"measured": True, "discovery_pct": 75, "pitching_pct": 25, "flagged": False, "flag": ""},
        "prescription": {"deal_overview": ["a"], "demo_agenda": ["Step one", "Step two"],
                         "demo_prescription": [{"step": "Step one", "points": ["p"]}], "market_context": ["m"]},
        "gate_overridden": False,
    }
    deal.update(extra)
    return deal


class SQLiteStoreTests(unittest.TestCase):
    def test_round_trip(self):
        store = SQLiteDealStore(os.path.join(tempfile.mkdtemp(), "t.db"))
        deal_id = store.save_deal(make_deal(gate_overridden=True))
        [saved] = store.list_deals()
        self.assertEqual(saved["id"], deal_id)
        self.assertEqual(saved["meddic"]["Metrics"]["status"], "GREEN")
        self.assertEqual(saved["prescription"]["demo_agenda"], ["Step one", "Step two"])
        self.assertIs(saved["gate_overridden"], True)

    def test_update_prescription_overwrites(self):
        store = SQLiteDealStore(os.path.join(tempfile.mkdtemp(), "t.db"))
        deal_id = store.save_deal(make_deal())
        refined = dict(make_deal()["prescription"], demo_agenda=["Refined step", "Another step"])
        self.assertTrue(store.update_prescription(deal_id, refined))
        self.assertFalse(store.update_prescription(999, refined))
        [saved] = store.list_deals()
        self.assertEqual(saved["prescription"]["demo_agenda"], ["Refined step", "Another step"])


class CRMPayloadTests(unittest.TestCase):
    def test_payload_shape(self):
        payload = to_crm_payload(dict(make_deal(), id=7))
        self.assertEqual(payload["external_id"], "meddic-tool-7")
        self.assertEqual(payload["opportunity"]["name"], "Northgate SaaS")
        self.assertEqual(set(payload["meddic"]), {"metrics", "economic_buyer", "decision_criteria",
                                                  "decision_process", "identify_pain", "champion"})
        self.assertEqual(payload["meddic"]["metrics"]["status"], "GREEN")
        self.assertTrue(payload["readiness"]["ready_to_demo"])
        self.assertEqual(payload["demo_plan"]["agenda"], ["Step one", "Step two"])
        self.assertEqual(payload["call_balance"]["pitching_pct"], 25)
        json.dumps(payload)  # must be serialisable

    def test_readiness_is_derived_from_statuses(self):
        payload = to_crm_payload(dict(make_deal("RED", gate_overridden=True), id=1))
        self.assertFalse(payload["readiness"]["ready_to_demo"])
        self.assertEqual(payload["readiness"]["missing_elements"], ["Metrics"])
        self.assertTrue(payload["readiness"]["gate_overridden"])

    def test_tolerates_partial_deal(self):
        payload = to_crm_payload({"id": 2, "buyer": "", "meddic": None, "prescription": None, "call_balance": None})
        self.assertEqual(payload["opportunity"]["name"], "Unnamed opportunity")
        self.assertFalse(payload["readiness"]["ready_to_demo"])
        self.assertEqual(len(payload["readiness"]["missing_elements"]), 6)


class StoreSelectionTests(unittest.TestCase):
    def test_backend_selection(self):
        tmp = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"STORAGE_BACKEND": "crm_mock", "CRM_OUTBOX_PATH": os.path.join(tmp, "o.jsonl")}):
            store = get_store()
            self.assertIsInstance(store, CRMDealStore)
            store.save_deal(make_deal())
            [payload] = store.list_deals()
            self.assertEqual(payload["external_id"], "meddic-tool-1")
            refined = dict(make_deal()["prescription"], demo_agenda=["Refined step", "Another step"])
            self.assertTrue(store.update_prescription(1, refined))
            [payload] = store.list_deals()  # upsert: still one deal, now refined
            self.assertEqual(payload["demo_plan"]["agenda"], ["Refined step", "Another step"])
            self.assertEqual(payload["opportunity"]["name"], "Northgate SaaS")
        with mock.patch.dict(os.environ, {"STORAGE_BACKEND": "sqlite", "DB_PATH": os.path.join(tmp, "s.db")}):
            self.assertIsInstance(get_store(), SQLiteDealStore)
        with mock.patch.dict(os.environ, {"STORAGE_BACKEND": "postgres"}):
            with self.assertRaises(ValueError):
                get_store()


class ExportScriptTests(unittest.TestCase):
    def test_export_writes_payload_array(self):
        tmp = tempfile.mkdtemp()
        db, out = os.path.join(tmp, "e.db"), os.path.join(tmp, "out.json")
        SQLiteDealStore(db).save_deal(make_deal())
        subprocess.run([sys.executable, "export_deals.py", "--db", db, "--out", out], cwd=ROOT, check=True,
                       capture_output=True)
        with open(out) as f:
            payloads = json.load(f)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["external_id"], "meddic-tool-1")


if __name__ == "__main__":
    unittest.main()
