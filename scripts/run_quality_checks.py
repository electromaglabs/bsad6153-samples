"""Run every check in db/quality_checks.sql and print the results as dated Markdown tables.

    python scripts/run_quality_checks.py > quality_output.md

Runs as app_reader (APP_DATABASE_URL) in a read-only transaction. Paste the tables you need
into docs/data_quality.md; each one carries the date it was measured.
"""

import os
import re
import sys
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

SQL_FILE = Path(__file__).resolve().parent.parent / "db" / "quality_checks.sql"


def checks():
    """Split the file on '-- name:' lines into (name, sql) pairs."""
    parts = re.split(r"^-- name:\s*(.+)$", SQL_FILE.read_text(encoding="utf-8"), flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1].strip().rstrip(";")) for i in range(1, len(parts), 2)]


def main():
    load_dotenv()
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        print("[FAIL] APP_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    today = date.today().isoformat()
    with psycopg.connect(url, connect_timeout=10) as conn:
        for name, query in checks():
            conn.execute("set transaction read only")
            cur = conn.execute(query)
            rows = cur.fetchall()
            conn.rollback()
            headers = [d.name for d in cur.description]
            print(f"### {name} (measured {today})\n")
            print("| " + " | ".join(headers) + " |")
            print("|" + "---|" * len(headers))
            for row in rows:
                print("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
            if not rows:
                print("| (no rows) |")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
