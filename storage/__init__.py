"""Pick the deal store from the environment.

STORAGE_BACKEND=sqlite (default)  -> SQLiteDealStore at DB_PATH (default insights.db)
STORAGE_BACKEND=crm_mock          -> CRMDealStore writing to CRM_OUTBOX_PATH (default crm_outbox.jsonl)
"""
import os

from storage.crm_mock import CRMDealStore, to_crm_payload
from storage.sqlite_store import SQLiteDealStore

__all__ = ["get_store", "to_crm_payload"]


def get_store():
    backend = os.getenv("STORAGE_BACKEND", "sqlite")
    if backend == "sqlite":
        return SQLiteDealStore(os.getenv("DB_PATH", "insights.db"))
    if backend == "crm_mock":
        return CRMDealStore(os.getenv("CRM_OUTBOX_PATH", "crm_outbox.jsonl"))
    raise ValueError(f"Unknown STORAGE_BACKEND {backend!r} (expected 'sqlite' or 'crm_mock')")
