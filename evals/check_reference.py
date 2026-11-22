"""Run every golden question's reference SQL and confirm it works (Milestone 3, Part F).

    python evals/check_reference.py

- Checks the set itself: at least 15 questions, 8 from the baseline list, 3 should_decline.
- Runs each reference query as app_reader (APP_DATABASE_URL), inside a READ ONLY transaction,
  so a reference query can never change data even by mistake.
- Confirms each query succeeds and returns at least one row.
- Saves the answers to evals/results/reference_<UTC time>.csv and compares them with the
  previous results file, listing which answers changed since then.

Exit code 0 when every query passes, 1 otherwise.
"""

import csv
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

EVALS_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = EVALS_DIR / "golden_questions.csv"
RESULTS_DIR = EVALS_DIR / "results"
COLUMNS = ["id", "question", "category", "reference_sql", "correct_behavior", "source"]
CATEGORIES = {"lookup", "aggregate", "trend", "compare", "should_decline"}


def check_question_set(questions):
    """Return a list of problems with the CSV itself (empty when it meets the requirements)."""
    problems = []
    if len(questions) < 15:
        problems.append(f"only {len(questions)} questions (need 15)")
    if sum(q["source"] == "baseline" for q in questions) < 8:
        problems.append("fewer than 8 questions with source = baseline")
    if sum(q["category"] == "should_decline" for q in questions) < 3:
        problems.append("fewer than 3 should_decline questions")
    for q in questions:
        if q["category"] not in CATEGORIES:
            problems.append(f"{q['id']}: unknown category {q['category']!r}")
        if q["category"] == "should_decline" and q["reference_sql"].strip():
            problems.append(f"{q['id']}: should_decline questions must have empty reference_sql")
        if q["category"] != "should_decline" and not q["reference_sql"].strip():
            problems.append(f"{q['id']}: missing reference_sql")
    return problems


def fingerprint(rows):
    """A short hash of the full result, so two runs can be compared without storing every row."""
    text = json.dumps(rows, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def previous_results():
    """{id: fingerprint} from the newest earlier results file, plus that file's name."""
    files = sorted(RESULTS_DIR.glob("reference_*.csv"))
    if not files:
        return {}, None
    with files[-1].open(encoding="utf-8") as f:
        return {row["id"]: row["fingerprint"] for row in csv.DictReader(f)}, files[-1].name


def main():
    load_dotenv()
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        print("[FAIL] APP_DATABASE_URL is not set. Add it to your .env file (see .env.example).")
        return 1

    with QUESTIONS_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            print(f"[FAIL] {QUESTIONS_FILE.name} columns must be: {', '.join(COLUMNS)}")
            return 1
        questions = list(reader)

    problems = check_question_set(questions)
    for problem in problems:
        print(f"[FAIL] {problem}")

    before, before_name = previous_results()
    checked_at = datetime.now(UTC)
    results, failures = [], 0

    try:
        conn = psycopg.connect(url, connect_timeout=10)
    except psycopg.OperationalError as error:
        print(f"[FAIL] Could not connect using APP_DATABASE_URL: {str(error).strip().splitlines()[0]}")
        return 1

    with conn:
        user = conn.execute("select current_user").fetchone()[0]
        conn.rollback()
        print(f"Connected as {user}. Checking {len(questions)} questions.\n")

        for q in questions:
            if q["category"] == "should_decline":
                print(f"[skip] {q['id']} should_decline (no SQL; judged on behavior)")
                continue
            try:
                conn.execute("set transaction read only")
                cur = conn.execute(q["reference_sql"])
                rows = cur.fetchall()
                columns = [d.name for d in cur.description]
            except psycopg.Error as error:
                conn.rollback()
                failures += 1
                print(f"[FAIL] {q['id']} query error: {str(error).strip().splitlines()[0]}")
                continue
            finally:
                if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                    conn.rollback()

            fp = fingerprint(rows)
            first = dict(zip(columns, rows[0], strict=True)) if rows else {}
            status = "ok" if rows else "EMPTY"
            if not rows:
                failures += 1
            change = ""
            if q["id"] in before:
                change = "unchanged" if before[q["id"]] == fp else "CHANGED"
            print(f"[{status:>4}] {q['id']} {len(rows):>5} rows  {change}")
            results.append(
                {
                    "id": q["id"],
                    "rows": len(rows),
                    "fingerprint": fp,
                    "change": change,
                    "first_row": json.dumps(first, default=str),
                }
            )

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"reference_{checked_at:%Y%m%dT%H%M%SZ}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "rows", "fingerprint", "change", "first_row"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nSaved {out.relative_to(EVALS_DIR.parent)}")
    if before_name:
        changed = [r["id"] for r in results if r["change"] == "CHANGED"]
        print(f"Compared with {before_name}: {len(changed)} changed ({', '.join(changed) or 'none'})")
    else:
        print("No earlier results file: this run is your baseline.")

    if failures or problems:
        print(f"\n[FAIL] {failures} query failure(s), {len(problems)} problem(s) with the question set.")
        return 1
    print("\n[ok] Every reference query ran and returned rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
