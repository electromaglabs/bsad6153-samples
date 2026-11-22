"""When was my data last successfully updated, and what changed in the last 7 days? (Milestone 3, Part C)

    python scripts/status.py

Reads sync_runs and the data tables as app_reader (APP_DATABASE_URL), the same read-only
role the website and chatbot will use. Times are shown in US Central time, the business's time zone.
"""

import os
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv

LOCAL_TIME_ZONE = ZoneInfo("America/Chicago")
# The sync runs every 12 hours. Allow for one missed run plus GitHub's scheduling delays
# before calling the data stale.
STALE_AFTER_HOURS = 30

LAST_SUCCESS = """
    select finished_at, records_inserted, records_updated, records_deleted, watermark
    from sync_runs
    where status = 'success'
    order by finished_at desc
    limit 1
"""

LAST_RUN = """
    select run_id, started_at, finished_at, status, trigger, error_message
    from sync_runs
    order by started_at desc
    limit 1
"""

RUNS_LAST_7_DAYS = """
    select status, count(*), sum(records_fetched), sum(records_inserted),
           sum(records_updated), sum(records_deleted)
    from sync_runs
    where started_at >= now() - interval '7 days'
    group by status
    order by status
"""

# first_seen_at is set once, when a row is first inserted; last_updated_at moves only when a
# value actually changes. So "new" and "changed" can be told apart.
DATA_CHANGES_LAST_7_DAYS = """
    select 'applications' as table_name,
           count(*) filter (where first_seen_at >= now() - interval '7 days') as new_rows,
           count(*) filter (where first_seen_at < now() - interval '7 days'
                            and last_updated_at >= now() - interval '7 days') as changed_rows
    from applications
    union all
    select 'service_requests',
           count(*) filter (where first_seen_at >= now() - interval '7 days'),
           count(*) filter (where first_seen_at < now() - interval '7 days'
                            and last_updated_at >= now() - interval '7 days')
    from service_requests
"""


def local(ts):
    return ts.astimezone(LOCAL_TIME_ZONE).strftime("%Y-%m-%d %I:%M %p %Z") if ts else "(not finished)"


def main():
    load_dotenv()
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        print("[FAIL] APP_DATABASE_URL is not set. Add it to your .env file (see .env.example).")
        return 1

    try:
        with psycopg.connect(url, connect_timeout=10) as conn:
            last_success = conn.execute(LAST_SUCCESS).fetchone()
            last_run = conn.execute(LAST_RUN).fetchone()
            runs = conn.execute(RUNS_LAST_7_DAYS).fetchall()
            changes = conn.execute(DATA_CHANGES_LAST_7_DAYS).fetchall()
    except psycopg.OperationalError as error:
        print("[FAIL] Could not connect using APP_DATABASE_URL.")
        print(f"       {str(error).strip().splitlines()[0]}")
        return 1

    print("DATA FRESHNESS")
    if last_success is None:
        print("  No successful sync yet.")
    else:
        finished_at, inserted, updated, deleted, watermark = last_success
        age_hours = (datetime.now(UTC) - finished_at).total_seconds() / 3600
        print(f"  Last successful update: {local(finished_at)} ({age_hours:.1f} hours ago)")
        print(f"  That run: {inserted} inserted, {updated} updated, {deleted} deleted")
        print(f"  Newest USAC change stored: {local(watermark)}")
        if age_hours > STALE_AFTER_HOURS:
            print(f"  WARNING: data is more than {STALE_AFTER_HOURS} hours old. Check the Actions tab.")

    if last_run is not None:
        run_id, started_at, finished_at, status, trigger, error_message = last_run
        print(f"\n  Most recent run: #{run_id}, {status}, {trigger}, started {local(started_at)}")
        if error_message:
            print(f"  Error: {error_message}")

    print("\nRUNS IN THE LAST 7 DAYS")
    if not runs:
        print("  None.")
    for status, count, fetched, inserted, updated, deleted in runs:
        print(
            f"  {status:<8} {count:>3} runs: {fetched} fetched, {inserted} inserted, "
            f"{updated} updated, {deleted} deleted"
        )

    print("\nDATA CHANGED IN THE LAST 7 DAYS")
    for table_name, new_rows, changed_rows in changes:
        print(f"  {table_name:<17} {new_rows:>5} new, {changed_rows:>5} changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
