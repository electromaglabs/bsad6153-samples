"""
ingest/sync.py - Bring the database up to date with USAC's Form 470 data (Milestone 3).

One entry point that replaces running fetch.py and then load.py by hand. Each run:
  1. Writes a sync_runs row marked "failed, did not finish". It is updated at the end, so a run
     that crashes or is stopped still leaves a truthful row.
  2. Reads the watermark: the newest last_modified_date_time stored by the last successful run.
  3. Downloads only rows modified since (watermark - OVERLAP), with retries and backoff (fetch.py).
  4. Upserts everything in ONE transaction: new rows are inserted, changed rows updated,
     unchanged rows left alone. If any row breaks a constraint, nothing is saved, and the run
     is retried one application at a time so a single bad form can be skipped (status "partial").
  5. Deletes line items and RFP documents that disappeared from a re-fetched form.
  6. Records counts, the new watermark and the status in sync_runs.

Run it from the project folder with the virtual environment active:
    python ingest/sync.py                      # incremental run, logged as trigger = manual
    python ingest/sync.py --full               # ignore the watermark and re-check every record
    python ingest/sync.py --trigger schedule   # what GitHub Actions runs

Exit code: 0 for success or partial, 1 for failed, so GitHub Actions shows a red X and emails you.
"""

import argparse
import logging
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import psycopg
import requests
from dotenv import load_dotenv
from psycopg import sql

# Reuse the tested pieces from Milestones 1 and 2 instead of copying them.
from fetch import PAUSE_BETWEEN_REQUESTS, USER_AGENT, get_with_retries
from load import (
    USAC_TIME_ZONE,
    attach_ids,
    build_applicants,
    build_applications,
    build_rfp_documents,
    build_service_requests,
    keep_preferred_version,
    to_eastern,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
STATES = ["OK", "KS"]
FIRST_FUNDING_YEAR = 2026
PAGE_SIZE = 500

# Re-check a week of changes before the watermark on every run. USAC publishes once a day, so a
# change can appear in the dataset after we have already stored newer ones. The overlap catches
# those late arrivals; the upsert makes re-checking harmless (unchanged rows are not touched).
OVERLAP = timedelta(days=7)

# Which columns identify a row (the natural key) and which ones can change, per table.
TABLES = {
    "applicants": (
        ["billed_entity_number"],
        ["name", "applicant_type", "address_1", "city", "state", "zip", "phone"],
    ),
    "applications": (
        ["application_number"],
        [
            "applicant_id",
            "form_version",
            "form_nickname",
            "funding_year",
            "status",
            "certified_at",
            "last_modified_at",
            "allowable_contract_date",
            "number_of_eligible_entities",
            "contact_name",
            "contact_email",
            "contact_phone",
            "consulting_firm_data",
            "category_one_description",
            "category_two_description",
        ],
    ),
    "service_requests": (
        ["application_id", "usac_line_number"],
        [
            "service_category",
            "service_type",
            "function",
            "quantity",
            "unit",
            "manufacturer",
            "other_manufacturer",
            "minimum_capacity",
            "maximum_capacity",
            "installation_initial",
            "rfp_attachment_count",
        ],
    ),
    "rfp_documents": (["service_request_id", "url"], ["uploaded_at"]),
}

log = logging.getLogger("sync")


class FetchError(Exception):
    """USAC could not be reached or refused the request, even after retries."""


# ---------------------------------------------------------------------------
# Fetching only what changed
# ---------------------------------------------------------------------------
def funding_years():
    """2026 through next year, so new funding years are picked up without editing the code."""
    return [str(year) for year in range(FIRST_FUNDING_YEAR, datetime.now(UTC).year + 2)]


def build_where(since):
    """The SoQL filter. Every value comes from our own constants or a datetime, never from input."""
    states = ",".join(f"'{s}'" for s in STATES)
    years = ",".join(f"'{y}'" for y in funding_years())
    where = f"billed_entity_state in({states}) AND funding_year in({years})"
    if since is not None:
        # USAC's timestamps are US Eastern without a zone, so compare in that same form.
        local = since.astimezone(USAC_TIME_ZONE).strftime("%Y-%m-%dT%H:%M:%S")
        where += f" AND last_modified_date_time > '{local}'"
    return where


def fetch_rows(session, where, stats):
    """Page through the matching rows. Raises FetchError if a page fails after all retries."""
    rows, offset = [], 0
    while True:
        params = {"$where": where, "$order": ":id", "$limit": PAGE_SIZE, "$offset": offset}
        page = get_with_retries(session, params, stats)  # retries 429 and 5xx with backoff
        if page is None:
            raise FetchError(f"USAC request failed at offset {offset} (see the log for the HTTP status)")
        rows.extend(page)
        log.info("Fetched %d rows (total %d)", len(page), len(rows))
        if len(page) < PAGE_SIZE:  # a short page means we reached the end
            return rows
        offset += PAGE_SIZE
        time.sleep(PAUSE_BETWEEN_REQUESTS)


def build_all(rows):
    """Turn API rows into table rows with the Milestone 2 functions."""
    kept = keep_preferred_version(rows)
    # build_applicants expects a "last_modified" field; the raw rows call it last_modified_date_time.
    applicant_rows = [{**r, "last_modified": r.get("last_modified_date_time", "")} for r in rows]
    return {
        "applicants": build_applicants(applicant_rows),
        "applications": build_applications(kept),
        "service_requests": build_service_requests(kept),
        "rfp_documents": build_rfp_documents(kept),
    }


def subset(data, app_numbers):
    """Only the rows belonging to some applications (used when retrying one form at a time)."""
    applications = [a for a in data["applications"] if a["application_number"] in app_numbers]
    bens = {a["billed_entity_number"] for a in applications}
    return {
        "applicants": [a for a in data["applicants"] if a["billed_entity_number"] in bens],
        "applications": applications,
        "service_requests": [r for r in data["service_requests"] if r["application_number"] in app_numbers],
        "rfp_documents": [d for d in data["rfp_documents"] if d["application_number"] in app_numbers],
    }


# ---------------------------------------------------------------------------
# Upserting
# ---------------------------------------------------------------------------
def upsert_statement(table, key_columns, value_columns):
    """Build the upsert for one table. For applicants it produces:

        insert into applicants as t (billed_entity_number, name, ..., phone)
        values (%(billed_entity_number)s, %(name)s, ..., %(phone)s)
        on conflict (billed_entity_number) do update
            set name = excluded.name, ..., phone = excluded.phone, last_updated_at = now()
            where (t.name, ..., t.phone) is distinct from (excluded.name, ..., excluded.phone)
        returning (t.xmax = 0) as inserted

    - "on conflict ... do update": if the natural key already exists, update instead of failing.
    - "excluded" is the row we tried to insert, i.e. the new values from USAC.
    - The "where ... is distinct from" clause updates the row ONLY if a value really changed, so a
      rerun changes nothing and last_updated_at keeps its meaning. ("is distinct from" treats two
      NULLs as equal, unlike "<>".) first_seen_at is never in the update, so it keeps the insert time.
    - "returning (t.xmax = 0)" is true for a freshly inserted row and false for an updated one,
      which is how we count inserts and updates separately. Unchanged rows return nothing.
    Table and column names come from the TABLES constant and are quoted with sql.Identifier.
    """
    ident = sql.Identifier
    columns = key_columns + value_columns
    return sql.SQL(
        "insert into {table} as t ({columns}) values ({values}) "
        "on conflict ({keys}) do update set {updates}, last_updated_at = now() "
        "where ({old}) is distinct from ({new}) "
        "returning (t.xmax = 0) as inserted"
    ).format(
        table=ident(table),
        columns=sql.SQL(", ").join(map(ident, columns)),
        values=sql.SQL(", ").join(map(sql.Placeholder, columns)),
        keys=sql.SQL(", ").join(map(ident, key_columns)),
        updates=sql.SQL(", ").join(sql.SQL("{0} = excluded.{0}").format(ident(c)) for c in value_columns),
        old=sql.SQL(", ").join(sql.SQL("t.{}").format(ident(c)) for c in value_columns),
        new=sql.SQL(", ").join(sql.SQL("excluded.{}").format(ident(c)) for c in value_columns),
    )


def upsert(cur, table, rows, counts):
    """Upsert rows into one table and add the inserted/updated numbers to counts."""
    if not rows:
        return
    key_columns, value_columns = TABLES[table]
    cur.executemany(upsert_statement(table, key_columns, value_columns), rows, returning=True)
    while True:  # one result per row sent: (True,) inserted, (False,) updated, or empty if unchanged
        result = cur.fetchone()
        if result is not None:
            counts[table]["inserted" if result[0] else "updated"] += 1
        if not cur.nextset():
            break


# A form that was re-fetched is complete (all its rows share one last_modified time), so any line
# item or attachment we hold for it that USAC no longer lists was removed at the source.
DELETE_STALE_DOCUMENTS = """
    delete from rfp_documents d
    using service_requests sr, applications a
    where d.service_request_id = sr.service_request_id
      and sr.application_id = a.application_id
      and a.application_number = any(%(apps)s::text[])
      and a.application_number || ':' || sr.usac_line_number || ':' || d.url <> all(%(keys)s::text[])
"""

DELETE_STALE_LINES = """
    delete from service_requests sr
    using applications a
    where sr.application_id = a.application_id
      and a.application_number = any(%(apps)s::text[])
      and a.application_number || ':' || sr.usac_line_number <> all(%(keys)s::text[])
"""


def write(cur, data, counts):
    """Write one batch, parents before children so every foreign key already exists."""
    upsert(cur, "applicants", data["applicants"], counts)
    bens = [a["billed_entity_number"] for a in data["applicants"]]
    cur.execute(
        "select billed_entity_number, applicant_id from applicants where billed_entity_number = any(%s)", (bens,)
    )
    applications = attach_ids(
        data["applications"], dict(cur.fetchall()), ["billed_entity_number"], "applicant_id", "applications"
    )
    upsert(cur, "applications", applications, counts)

    app_numbers = [a["application_number"] for a in data["applications"]]
    cur.execute(
        "select application_number, application_id from applications where application_number = any(%s)", (app_numbers,)
    )
    requests_ready = attach_ids(
        data["service_requests"], dict(cur.fetchall()), ["application_number"], "application_id", "service_requests"
    )
    upsert(cur, "service_requests", requests_ready, counts)

    cur.execute(
        """select a.application_number, sr.usac_line_number, sr.service_request_id
           from service_requests sr join applications a on a.application_id = sr.application_id
           where a.application_number = any(%s)""",
        (app_numbers,),
    )
    request_ids = {(app, line): sr_id for app, line, sr_id in cur.fetchall()}
    documents = attach_ids(
        data["rfp_documents"],
        request_ids,
        ["application_number", "usac_line_number"],
        "service_request_id",
        "rfp_documents",
    )
    upsert(cur, "rfp_documents", documents, counts)

    # Children first, so the line-item delete doesn't remove documents through the cascade uncounted.
    document_keys = [f"{d['application_number']}:{d['usac_line_number']}:{d['url']}" for d in data["rfp_documents"]]
    cur.execute(DELETE_STALE_DOCUMENTS, {"apps": app_numbers, "keys": document_keys})
    counts["rfp_documents"]["deleted"] += cur.rowcount
    line_keys = [f"{r['application_number']}:{r['usac_line_number']}" for r in data["service_requests"]]
    cur.execute(DELETE_STALE_LINES, {"apps": app_numbers, "keys": line_keys})
    counts["service_requests"]["deleted"] += cur.rowcount


def new_counts():
    return {table: {"inserted": 0, "updated": 0, "deleted": 0} for table in TABLES}


def add_counts(total, part):
    for table in TABLES:
        for kind in ("inserted", "updated", "deleted"):
            total[table][kind] += part[table][kind]


def total(counts, kind):
    return sum(counts[table][kind] for table in TABLES)


# ---------------------------------------------------------------------------
# sync_runs bookkeeping
# ---------------------------------------------------------------------------
def start_run(conn, trigger):
    """Insert this run's row right away (committed on its own, outside the data transaction)."""
    return conn.execute(
        "insert into sync_runs (status, trigger, error_message) "
        "values ('failed', %s, 'Run did not finish (stopped or crashed before the end).') returning run_id",
        (trigger,),
    ).fetchone()[0]


def last_watermark(conn):
    """The watermark of the most recent run that saved data (success or partial)."""
    row = conn.execute(
        "select watermark from sync_runs where status in ('success', 'partial') and watermark is not null "
        "order by started_at desc limit 1"
    ).fetchone()
    return row[0] if row else None


def finish_run(conn, run_id, status, fetched, counts, watermark, error_message):
    conn.execute(
        """update sync_runs
           set finished_at = now(), status = %s, records_fetched = %s, records_inserted = %s,
               records_updated = %s, records_deleted = %s, watermark = %s, error_message = %s
           where run_id = %s""",
        (
            status,
            fetched,
            total(counts, "inserted"),
            total(counts, "updated"),
            total(counts, "deleted"),
            watermark,
            error_message,
            run_id,
        ),
    )


def short_error(error):
    """One line, at most 500 characters. Our secrets live in headers and the connection string,
    which these messages don't include."""
    first_line = str(error).strip().splitlines()[0] if str(error).strip() else ""
    return f"{type(error).__name__}: {first_line}"[:500]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Sync E-Rate Form 470 data from USAC into the database.")
    parser.add_argument(
        "--trigger", choices=["manual", "schedule"], default="manual", help="Recorded in sync_runs (default: manual)"
    )
    parser.add_argument("--full", action="store_true", help="Ignore the watermark and re-check every record")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set (.env locally, an Actions secret on GitHub).")
        return 1

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip()
    if app_token:
        session.headers["X-App-Token"] = app_token  # sent as a header, never printed or logged
    else:
        log.warning("No SOCRATA_APP_TOKEN set - running unauthenticated (lower rate limits).")

    try:
        conn = psycopg.connect(url, connect_timeout=10, autocommit=True)
    except psycopg.OperationalError as error:
        log.error("Could not connect to the database: %s", short_error(error))
        return 1  # nowhere to log the run, but the red X in Actions still shows the failure

    with conn:
        run_id = start_run(conn, args.trigger)
        log.info("Started sync run #%d (trigger: %s)", run_id, args.trigger)
        rows, counts, previous = [], new_counts(), None
        try:
            previous = last_watermark(conn)
            since = None if args.full or previous is None else previous - OVERLAP
            log.info("Watermark: %s. Fetching changes since: %s", previous, since or "the beginning (full run)")

            http_stats = {
                k: 0
                for k in [
                    "requests",
                    "timeouts",
                    "connection_errors",
                    "rate_limited",
                    "server_errors",
                    "client_errors",
                    "bad_json",
                    "failed_pages",
                ]
            }
            rows = fetch_rows(session, build_where(since), http_stats)
            log.info("HTTP: %s", http_stats)
            data = build_all(rows)

            skipped = []
            try:
                # The whole batch in ONE transaction: it commits only if every statement succeeds.
                with conn.transaction(), conn.cursor() as cur:
                    write(cur, data, counts)
            except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as error:
                log.warning("Batch rolled back (%s). Retrying one application at a time.", short_error(error))
                counts = new_counts()
                with conn.transaction():
                    for app in data["applications"]:
                        number = app["application_number"]
                        part = new_counts()
                        try:
                            # A savepoint: a failure undoes only this application.
                            with conn.transaction(), conn.cursor() as cur:
                                write(cur, subset(data, {number}), part)
                        except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as app_error:
                            skipped.append(f"{number} ({app_error.diag.constraint_name or 'invalid value'})")
                            continue
                        add_counts(counts, part)

            fetched_max = max(
                (r["last_modified_date_time"] for r in rows if r.get("last_modified_date_time")), default=None
            )
            candidates = [w for w in (previous, to_eastern(fetched_max)) if w is not None]
            watermark = max(candidates) if candidates else None

            status = "partial" if skipped else "success"
            message = f"Skipped {len(skipped)} application(s): {', '.join(skipped[:10])}" if skipped else None
            finish_run(conn, run_id, status, len(rows), counts, watermark, message)
        except Exception as error:  # anything else: record it, then fail visibly
            log.error("Sync failed: %s", short_error(error))
            try:
                finish_run(conn, run_id, "failed", len(rows), new_counts(), previous, short_error(error))
            except psycopg.Error:
                log.error("Could not record the failure in sync_runs either.")
            return 1

    log.info("---------------- SUMMARY (run #%d: %s) ----------------", run_id, status)
    log.info("%-18s %9s %9s %9s", "table", "inserted", "updated", "deleted")
    for table in TABLES:
        c = counts[table]
        log.info("%-18s %9d %9d %9d", table, c["inserted"], c["updated"], c["deleted"])
    log.info("API rows fetched: %d. New watermark: %s", len(rows), watermark)
    if skipped:
        log.warning(message)
        if os.getenv("GITHUB_ACTIONS") == "true":
            print(f"::warning::Sync run #{run_id} was partial. {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
