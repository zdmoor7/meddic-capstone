"""Mock CRM adapter.

to_crm_payload() maps a saved deal to a CRM-friendly JSON payload. The
mock store "sends" each payload by appending it to a local JSONL outbox
instead of calling a CRM.

Plugging in a real CRM:
  1. Subclass CRMDealStore (or edit it) and replace _send() with the API
     call, e.g. a Salesforce Opportunity upsert keyed on external_id, or a
     HubSpot deals create/update. Map the payload's fields to the CRM's
     custom fields there; keep to_crm_payload() CRM-neutral.
  2. Add the CRM credentials to .env and read them in __init__.
  3. Select it with STORAGE_BACKEND (see storage/__init__.py).
Keep SQLite as the system of record if the CRM call can fail or be slow:
save locally first, then push, so a CRM outage never loses a deal.
"""
import json
import os

from meddic import MEDDIC_ELEMENTS, build_gate
from storage.base import DealStore

SCHEMA_VERSION = 1


def _snake(name):
    return name.lower().replace(" ", "_")


def to_crm_payload(deal):
    meddic = deal.get("meddic") or {}
    prescription = deal.get("prescription") or {}
    balance = deal.get("call_balance") or {}
    # Readiness is derived from the statuses, not trusted from the client.
    gate = build_gate({name: meddic.get(name) or {"status": "RED", "follow_up_questions": []}
                       for name in MEDDIC_ELEMENTS})
    return {
        "external_id": f"meddic-tool-{deal.get('id')}",
        "opportunity": {
            "name": deal.get("buyer") or "Unnamed opportunity",
            "created_at": deal.get("created_at"),
            "ready_to_demo": gate["ready"],
        },
        "meddic": {
            _snake(name): {
                "summary": (meddic.get(name) or {}).get("content", ""),
                "status": (meddic.get(name) or {}).get("status", "RED"),
                "follow_up_questions": (meddic.get(name) or {}).get("follow_up_questions", []),
            }
            for name in MEDDIC_ELEMENTS
        },
        "readiness": {
            "ready_to_demo": gate["ready"],
            "missing_elements": [m["element"] for m in gate["missing"]],
            "gate_overridden": bool(deal.get("gate_overridden")),
        },
        "call_balance": {
            "measured": balance.get("measured", False),
            "discovery_pct": balance.get("discovery_pct"),
            "pitching_pct": balance.get("pitching_pct"),
            "flagged": balance.get("flagged", False),
            "flag": balance.get("flag", ""),
        },
        "demo_plan": {
            "deal_overview": prescription.get("deal_overview", []),
            "agenda": prescription.get("demo_agenda", []),
            "steps": prescription.get("demo_prescription", []),
            "market_context": prescription.get("market_context", []),
        },
        "source": {"system": "meddic-discovery-tool", "schema_version": SCHEMA_VERSION},
    }


class CRMDealStore(DealStore):
    """Mock CRM: writes payloads to a JSONL outbox instead of calling a CRM API."""

    def __init__(self, outbox_path):
        self.outbox_path = outbox_path

    def _send(self, payload):
        # Real integration goes here (see module docstring).
        with open(self.outbox_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def list_deals(self):
        if not os.path.exists(self.outbox_path):
            return []
        with open(self.outbox_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def save_deal(self, deal):
        deal_id = len(self.list_deals()) + 1
        self._send(to_crm_payload(dict(deal, id=deal_id)))
        return deal_id
