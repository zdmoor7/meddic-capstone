"""Export saved deals as CRM JSON payloads.

Reads the SQLite store (the system of record) and maps each deal with
storage.crm_mock.to_crm_payload. Writes a JSON array to --out, or stdout.
"""
import argparse
import json
import os
import sys

from storage import to_crm_payload
from storage.sqlite_store import SQLiteDealStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("DB_PATH", "insights.db"))
    parser.add_argument("--out", help="file to write; defaults to stdout")
    args = parser.parse_args()

    payloads = [to_crm_payload(deal) for deal in SQLiteDealStore(args.db).list_deals()]
    text = json.dumps(payloads, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"Wrote {len(payloads)} deal(s) to {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
