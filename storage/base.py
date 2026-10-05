"""Storage adapter interface for saved deals.

A deal is a plain dict:
    {
        "id": int | None,
        "buyer": str,
        "created_at": ISO-8601 str,
        "meddic": {element: {"content", "flag", "status", "follow_up_questions"}},
        "call_balance": dict (see meddic.build_call_balance),
        "prescription": dict (see prescription.parse_prescription_response),
        "gate_overridden": bool,
    }
"""
from abc import ABC, abstractmethod


class DealStore(ABC):
    @abstractmethod
    def save_deal(self, deal):
        """Persist a deal and return its id."""

    @abstractmethod
    def list_deals(self):
        """Return all saved deals, oldest first."""

    @abstractmethod
    def update_prescription(self, deal_id, prescription):
        """Overwrite a saved deal's prescription (e.g. after the SE refines it). Returns True if found."""
