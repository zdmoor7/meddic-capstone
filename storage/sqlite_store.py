import json
import sqlite3

from storage.base import DealStore

JSON_FIELDS = ("meddic", "call_balance", "prescription")


class SQLiteDealStore(DealStore):
    """Default store: one row per deal, structured fields kept as JSON text."""

    def __init__(self, path):
        self.path = path
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS deals ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, buyer TEXT, created_at TEXT, "
                "meddic TEXT, call_balance TEXT, prescription TEXT, gate_overridden INTEGER)"
            )

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_deal(self, deal):
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO deals (buyer, created_at, meddic, call_balance, prescription, gate_overridden) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (deal["buyer"], deal["created_at"], *(json.dumps(deal.get(f)) for f in JSON_FIELDS),
                 int(bool(deal.get("gate_overridden")))),
            )
            return cur.lastrowid

    def update_prescription(self, deal_id, prescription):
        with self._connect() as conn:
            cur = conn.execute("UPDATE deals SET prescription = ? WHERE id = ?", (json.dumps(prescription), deal_id))
            return cur.rowcount == 1

    def list_deals(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM deals ORDER BY id").fetchall()
        deals = []
        for row in rows:
            deal = dict(row)
            for f in JSON_FIELDS:
                deal[f] = json.loads(deal[f]) if deal[f] else None
            deal["gate_overridden"] = bool(deal["gate_overridden"])
            deals.append(deal)
        return deals
