"""
ingest/fetch.py - Download E-Rate FCC Form 470 records from USAC Open Data (Socrata).

Dataset:  E-Rate Request for Services: FCC Form 470 (jt8s-3q52)
Docs:     https://dev.socrata.com/foundry/opendata.usac.org/jt8s-3q52
API:      SODA 2.1  ->  https://opendata.usac.org/resource/jt8s-3q52.json

What it fetches (two resource types from the same dataset):
  1. service_requests - the raw Form 470 rows. One row = one application x one
     service request x one RFP attachment. This is the main resource.
  2. applicants       - one row per billed entity (school, district, library,
     consortium), built by a separate GROUP BY query. Related to (1) through
     billed_entity_number.

Run it from the project folder with the virtual environment active:
    python ingest/fetch.py                       # OK + KS, funding years 2026 and 2027
    python ingest/fetch.py --states OK KS TX --years 2026 2027
    python ingest/fetch.py --page-size 200       # smaller pages = more requests
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
BASE_URL = "https://opendata.usac.org/resource/jt8s-3q52.json"
USER_AGENT = "bsad6153-erate-fetch/1.0 (student project; +https://github.com/electromaglabs/bsad6153-samples)"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"

REQUEST_TIMEOUT = 30  # seconds to wait for the server before giving up on one try
PAUSE_BETWEEN_REQUESTS = 1  # seconds to wait between successful requests (be polite)
MAX_RETRIES = 5  # tries per page before we give up on that page
BACKOFF_BASE = 2  # retry waits grow 2s, 4s, 8s, 16s ... (plus a little randomness)
BACKOFF_MAX = 60  # never wait longer than this between retries

# Fields we expect on every service-request row. Missing ones are counted and reported.
EXPECTED_FIELDS = [
    "application_number",
    "billed_entity_number",
    "billed_entity_name",
    "billed_entity_state",
    "funding_year",
    "service_request_id",
    "service_category",
    "service_type",
    "fcc_form_470_status",
    "last_modified_date_time",
]

log = logging.getLogger("fetch")


# ---------------------------------------------------------------------------
# HTTP: one GET with retries, backoff, and 429 handling
# ---------------------------------------------------------------------------
def get_with_retries(session, params, stats):
    """GET BASE_URL with params. Returns parsed JSON (a list) or None if every try failed."""
    for attempt in range(1, MAX_RETRIES + 1):
        stats["requests"] += 1
        try:
            resp = session.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.Timeout:
            stats["timeouts"] += 1
            wait = backoff_seconds(attempt)
            log.warning("Timeout (try %d/%d). Waiting %.1fs.", attempt, MAX_RETRIES, wait)
            time.sleep(wait)
            continue
        except requests.exceptions.ConnectionError as exc:
            stats["connection_errors"] += 1
            wait = backoff_seconds(attempt)
            log.warning("Connection error (try %d/%d): %s. Waiting %.1fs.", attempt, MAX_RETRIES, exc, wait)
            time.sleep(wait)
            continue

        # 429 Too Many Requests: we are being throttled. Wait and try again.
        if resp.status_code == 429:
            stats["rate_limited"] += 1
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait = min(int(retry_after), BACKOFF_MAX)  # server told us how long
            else:
                wait = backoff_seconds(attempt)  # it didn't, so back off ourselves
            log.warning("429 Too Many Requests (try %d/%d). Waiting %.1fs.", attempt, MAX_RETRIES, wait)
            time.sleep(wait)
            continue

        # 5xx: problem on the server's side. Usually temporary, so retry.
        if 500 <= resp.status_code < 600:
            stats["server_errors"] += 1
            wait = backoff_seconds(attempt)
            log.warning("Server error %d (try %d/%d). Waiting %.1fs.", resp.status_code, attempt, MAX_RETRIES, wait)
            time.sleep(wait)
            continue

        # Other 4xx: our request is wrong (bad query, bad token). Retrying won't help.
        if resp.status_code >= 400:
            stats["client_errors"] += 1
            log.error("HTTP %d - not retrying. Response: %s", resp.status_code, resp.text[:300])
            return None

        try:
            return resp.json()
        except ValueError:
            stats["bad_json"] += 1
            log.warning("Response was not valid JSON (try %d/%d).", attempt, MAX_RETRIES)
            time.sleep(backoff_seconds(attempt))

    log.error("Gave up after %d tries.", MAX_RETRIES)
    return None


def backoff_seconds(attempt):
    """Exponential backoff with jitter: about 2, 4, 8, 16, 32 seconds, capped at BACKOFF_MAX."""
    return min(BACKOFF_BASE**attempt, BACKOFF_MAX) + random.uniform(0, 1)


# ---------------------------------------------------------------------------
# Pagination: keep asking for the next page until a short/empty page comes back
# ---------------------------------------------------------------------------
def fetch_all_pages(session, base_params, page_size, out_dir, label, stats):
    """Page through results with $limit/$offset. Saves each page's raw JSON. Returns all records."""
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    offset = 0
    page = 1

    while True:
        params = dict(base_params)
        params["$limit"] = page_size
        params["$offset"] = offset

        log.info("[%s] page %d (offset %d)", label, page, offset)
        data = get_with_retries(session, params, stats)

        if data is None:
            stats["failed_pages"] += 1
            log.error("[%s] page %d failed; stopping this resource with %d records.", label, page, len(records))
            break

        # Save exactly what the API sent, before we touch it.
        page_file = out_dir / f"page_{page:03d}.json"
        page_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        records.extend(data)
        log.info(
            "[%s] got %d records (total %d) -> %s", label, len(data), len(records), page_file.relative_to(PROJECT_ROOT)
        )

        # A page with fewer rows than we asked for means we reached the end.
        if len(data) < page_size:
            break

        offset += page_size
        page += 1
        time.sleep(PAUSE_BETWEEN_REQUESTS)  # polite pause before the next page

    return records


# ---------------------------------------------------------------------------
# Data checks
# ---------------------------------------------------------------------------
def count_missing_fields(records, fields):
    """Return {field: number of records where it is missing or empty}."""
    missing = {f: 0 for f in fields}
    for rec in records:
        for f in fields:
            if rec.get(f) in (None, ""):
                missing[f] += 1
    return {f: n for f, n in missing.items() if n > 0}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Fetch E-Rate Form 470 data from USAC Open Data.")
    parser.add_argument("--states", nargs="+", default=["OK", "KS"], help="Two-letter states (default: OK KS)")
    parser.add_argument("--years", nargs="+", default=["2026", "2027"], help="Funding years (default: 2026 2027)")
    parser.add_argument("--page-size", type=int, default=500, help="Rows per request (default: 500)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    # --- Authentication: read the app token from .env (never print it) ---
    load_dotenv(PROJECT_ROOT / ".env")
    app_token = os.getenv("SOCRATA_APP_TOKEN", "").strip()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    if app_token:
        session.headers["X-App-Token"] = app_token
        log.info("Using SOCRATA_APP_TOKEN from .env.")
    else:
        log.warning("No SOCRATA_APP_TOKEN in .env - running unauthenticated (lower rate limits).")

    # --- Build the filter (values are validated to keep the query safe) ---
    states = [s.upper() for s in args.states if s.isalpha() and len(s) == 2]
    years = [y for y in args.years if y.isdigit() and len(y) == 4]
    if not states or not years:
        log.error("Need at least one valid state (e.g. OK) and year (e.g. 2027).")
        return 2
    state_list = ",".join(f"'{s}'" for s in states)
    year_list = ",".join(f"'{y}'" for y in years)
    where = f"billed_entity_state in({state_list}) AND funding_year in({year_list})"
    log.info("Filter: %s", where)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RAW_DIR / run_id
    stats = {
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

    # --- Resource 1: service-request rows (main resource) ---
    service_requests = fetch_all_pages(
        session,
        {"$where": where, "$order": ":id"},  # :id gives a stable order so pages don't overlap
        args.page_size,
        run_dir / "service_requests",
        "service_requests",
        stats,
    )

    # --- Resource 2: applicants (one row per billed entity), related by billed_entity_number ---
    time.sleep(PAUSE_BETWEEN_REQUESTS)
    applicants = fetch_all_pages(
        session,
        {
            "$select": "billed_entity_number, billed_entity_name, applicant_type, ben_address_1, "
            "billed_entity_city, billed_entity_state, billed_entity_zip, billed_entity_phone, "
            "count(*) AS service_request_rows, max(last_modified_date_time) AS last_modified",
            "$where": where,
            "$group": "billed_entity_number, billed_entity_name, applicant_type, ben_address_1, "
            "billed_entity_city, billed_entity_state, billed_entity_zip, billed_entity_phone",
            "$order": "billed_entity_number",
        },
        args.page_size,
        run_dir / "applicants",
        "applicants",
        stats,
    )

    # --- Checks and summary ---
    missing = count_missing_fields(service_requests, EXPECTED_FIELDS)
    unique_apps = len({r.get("application_number") for r in service_requests if r.get("application_number")})
    unique_bens = len({r.get("billed_entity_number") for r in service_requests if r.get("billed_entity_number")})
    orphans = {r.get("billed_entity_number") for r in service_requests} - {
        a.get("billed_entity_number") for a in applicants
    }

    summary = {
        "run_id": run_id,
        "filter": where,
        "page_size": args.page_size,
        "authenticated": bool(app_token),
        "counts": {
            "service_request_rows": len(service_requests),
            "unique_applications": unique_apps,
            "unique_billed_entities_in_rows": unique_bens,
            "applicant_rows": len(applicants),
            "rows_without_matching_applicant": len(orphans),
        },
        "missing_fields": missing,
        "http": stats,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Small sample for Git (data/raw/ is ignored; data/sample/ is committed)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    (SAMPLE_DIR / "service_requests_sample.json").write_text(
        json.dumps(service_requests[:3], indent=2), encoding="utf-8"
    )
    (SAMPLE_DIR / "applicants_sample.json").write_text(json.dumps(applicants[:3], indent=2), encoding="utf-8")

    log.info("---------------- SUMMARY ----------------")
    for k, v in summary["counts"].items():
        log.info("%-32s %s", k, v)
    log.info("missing fields: %s", missing or "none")
    log.info("http: %s", stats)
    log.info("raw files: %s", run_dir.relative_to(PROJECT_ROOT))

    if stats["failed_pages"] or len(service_requests) < 500:
        log.warning("Finished with problems (failed pages or fewer than 500 rows). See log above.")
        return 1
    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
