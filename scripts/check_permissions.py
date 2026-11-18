"""Prove that app_reader can read and nothing else (Milestone 3, Part A).

    python scripts/check_permissions.py

Connects with APP_DATABASE_URL and tries one SELECT, INSERT, UPDATE, and DELETE.
The SELECT should work; the other three should fail with "permission denied".
Every statement runs in its own transaction that is always rolled back, so even if
a permission were set wrong, this script could not change your data.
It never prints the connection string, which contains the password.
"""

import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

TESTS = [
    ("SELECT (should work)", "select count(*) from applicants"),
    (
        "INSERT (should fail)",
        "insert into applicants (billed_entity_number, name, applicant_type, city, state, zip) "
        "values ('999999999', 'Permission test', 'School', 'Test', 'OK', '00000')",
    ),
    ("UPDATE (should fail)", "update applicants set name = name"),
    ("DELETE (should fail)", "delete from applicants"),
]

url = os.environ.get("APP_DATABASE_URL")
if not url:
    print("[FAIL] APP_DATABASE_URL is not set. Add it to your .env file (see .env.example).")
    sys.exit(1)

try:
    conn = psycopg.connect(url, connect_timeout=10)
except psycopg.OperationalError as error:
    print("[FAIL] Could not connect using APP_DATABASE_URL.")
    print(f"       {str(error).strip().splitlines()[0]}")
    sys.exit(1)

with conn:
    user = conn.execute("select current_user").fetchone()[0]
    conn.rollback()
    print(f"Connected as database user: {user}\n")

    unexpected = 0
    for label, statement in TESTS:
        print(f"{label}\n  {statement}")
        try:
            cur = conn.execute(statement)
            result = cur.fetchone()[0] if cur.description else f"{cur.rowcount} rows affected"
            print(f"  -> OK: {result}")
            if "should fail" in label:
                unexpected += 1
        except psycopg.errors.InsufficientPrivilege as error:
            print(f"  -> ERROR: {error.diag.message_primary}")
            if "should work" in label:
                unexpected += 1
        finally:
            conn.rollback()  # undo anything, always
        print()

if unexpected:
    print(f"[FAIL] {unexpected} result(s) were not what app_reader should allow. Check db/roles.sql.")
    sys.exit(1)
print("[ok] app_reader can read and cannot change data.")
