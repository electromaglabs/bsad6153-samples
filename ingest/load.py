"""
ingest/load.py - Load raw Form 470 JSON (from ingest/fetch.py) into the database tables.

Reads one run folder under data/raw/ and fills the four tables in db/schema.sql,
parents before children so every foreign key already exists:

    applicants -> applications -> service_requests -> rfp_documents

Run it from the project folder with the virtual environment active:
    python ingest/load.py                                  # newest complete run in data/raw/
    python ingest/load.py --run data/raw/20261111T230329Z  # a specific run

Safe to run twice: every insert uses ON CONFLICT ... DO NOTHING on the table's natural key,
so a second run adds 0 rows. (Milestone 3 upgrades this to update rows that changed.)
Every value goes through psycopg placeholders (%(name)s); no SQL is built from data.
The whole load is one transaction: if any row breaks a constraint, nothing is saved.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv
from psycopg import sql

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# USAC sends times without a time zone. They are US Eastern, so we attach that zone
# before storing them as timestamptz.
USAC_TIME_ZONE = ZoneInfo("America/New_York")

TABLES = ["applicants", "applications", "service_requests", "rfp_documents"]

log = logging.getLogger("load")


# ---------------------------------------------------------------------------
# Small converters. Socrata leaves empty fields out of the JSON, and numbers,
# dates and booleans arrive as text, so every field is read with .get() and converted.
# ---------------------------------------------------------------------------
def clean(value):
    """Trim text; turn empty or missing values into None."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def to_eastern(text):
    """'2026-08-05T17:12:25.000' (no zone, US Eastern) -> timezone-aware datetime, or None."""
    if not text:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=USAC_TIME_ZONE)


def to_date(text):
    """'2026-09-02T00:00:00.000' -> date, or None."""
    return datetime.fromisoformat(text).date() if text else None


def to_int(text):
    return int(text) if text not in (None, "") else None


def to_bool(value):
    """'True' / 'False' (text) -> True / False; anything else -> None."""
    return {"true": True, "false": False}.get(str(value).strip().lower()) if value is not None else None


# ---------------------------------------------------------------------------
# Reading the run folder
# ---------------------------------------------------------------------------
def newest_complete_run():
    """The newest folder in data/raw/ that has a summary.json (fetch.py writes it last)."""
    runs = sorted(d for d in RAW_DIR.iterdir() if d.is_dir() and (d / "summary.json").exists())
    return runs[-1] if runs else None


def read_pages(folder):
    """All records from page_*.json files in one folder, in page order."""
    records = []
    for page in sorted(folder.glob("page_*.json")):
        records.extend(json.loads(page.read_text(encoding="utf-8")))
    return records


# ---------------------------------------------------------------------------
# Turning API rows into table rows (no database needed for this part)
# ---------------------------------------------------------------------------
def build_applicants(applicant_rows):
    """One row per BEN. The grouped query can return a BEN twice when its address or phone
    changed between filings; keep the version with the newest last_modified date."""
    newest = {}
    for row in applicant_rows:
        ben = clean(row.get("billed_entity_number"))
        if ben and (ben not in newest or row.get("last_modified", "") > newest[ben].get("last_modified", "")):
            newest[ben] = row
    return [
        {
            "billed_entity_number": ben,
            "name": clean(row.get("billed_entity_name")),
            "applicant_type": clean(row.get("applicant_type")),
            "address_1": clean(row.get("ben_address_1")),
            "city": clean(row.get("billed_entity_city")),
            "state": clean(row.get("billed_entity_state")),
            "zip": clean(row.get("billed_entity_zip")),
            "phone": clean(row.get("billed_entity_phone")),
        }
        for ben, row in newest.items()
    ]


def keep_preferred_version(service_rows):
    """Keep only rows from one version per application: Current if it exists, otherwise Original."""
    versions = {}
    for row in service_rows:
        versions.setdefault(row["application_number"], set()).add(row["form_version"])
    preferred = {app: ("Current" if "Current" in found else "Original") for app, found in versions.items()}
    return [row for row in service_rows if row["form_version"] == preferred[row["application_number"]]]


def build_applications(kept_rows):
    """One row per application number. Application-level fields repeat on every API row of a
    filing; if they ever differ, use the row with the newest last_modified_date_time."""
    newest = {}
    for row in kept_rows:
        app = row["application_number"]
        if app not in newest or row["last_modified_date_time"] > newest[app]["last_modified_date_time"]:
            newest[app] = row
    return [
        {
            "application_number": app,
            "billed_entity_number": clean(row.get("billed_entity_number")),
            "form_version": clean(row.get("form_version")),
            "form_nickname": clean(row.get("form_nickname")),
            "funding_year": to_int(row.get("funding_year")),
            "status": clean(row.get("fcc_form_470_status")),
            "certified_at": to_eastern(row.get("certified_date_time")),
            "last_modified_at": to_eastern(row.get("last_modified_date_time")),
            "allowable_contract_date": to_date(row.get("allowable_contract_date")),
            "number_of_eligible_entities": to_int(row.get("number_of_eligible_entities")),
            "contact_name": clean(row.get("contact_name")),
            "contact_email": clean(row.get("contact_email")),
            "contact_phone": clean(row.get("contact_phone")),
            "consulting_firm_data": clean(row.get("consulting_firm_data")),
            "category_one_description": clean(row.get("category_one_description")),
            "category_two_description": clean(row.get("category_two_description")),
        }
        for app, row in newest.items()
    ]


def build_service_requests(kept_rows):
    """One row per (application, USAC line number). The API repeats a request once per RFP
    attachment; those copies are identical apart from the attachment, so keep the first."""
    requests = {}
    for row in kept_rows:
        line = to_int(row.get("service_request_id"))
        if line is None:  # canceled forms have no service requests
            continue
        requests.setdefault((row["application_number"], line), row)
    return [
        {
            "application_number": app,
            "usac_line_number": line,
            "service_category": clean(row.get("service_category")),
            "service_type": clean(row.get("service_type")),
            "function": clean(row.get("function")),
            "quantity": to_int(row.get("quantity")),
            "unit": clean(row.get("unit")),
            "manufacturer": clean(row.get("manufacturer")),
            "other_manufacturer": clean(row.get("other_manufacturer")),
            "minimum_capacity": clean(row.get("minimum_capacity")),
            "maximum_capacity": clean(row.get("maximum_capacity")),
            "installation_initial": to_bool(row.get("installation_initial")),
            "rfp_attachment_count": to_int(row.get("service_request_rfp_attachment")) or 0,
        }
        for (app, line), row in requests.items()
    ]


def build_rfp_documents(kept_rows):
    """One row per (application, line number, attachment URL)."""
    documents = {}
    for row in kept_rows:
        line = to_int(row.get("service_request_id"))
        attachment = row.get("rfp_documents")
        url = clean(attachment.get("url")) if isinstance(attachment, dict) else None
        if line is None or url is None:
            continue
        documents.setdefault(
            (row["application_number"], line, url),
            {
                "application_number": row["application_number"],
                "usac_line_number": line,
                "url": url,
                "uploaded_at": to_eastern(row.get("rfp_upload_date")),
            },
        )
    return list(documents.values())


# ---------------------------------------------------------------------------
# SQL. Named placeholders (%(name)s) are filled by psycopg, never by string formatting.
# ---------------------------------------------------------------------------
INSERT_APPLICANT = """
    insert into applicants (billed_entity_number, name, applicant_type, address_1, city, state, zip, phone)
    values (%(billed_entity_number)s, %(name)s, %(applicant_type)s, %(address_1)s,
            %(city)s, %(state)s, %(zip)s, %(phone)s)
    on conflict (billed_entity_number) do nothing
"""

INSERT_APPLICATION = """
    insert into applications (
        application_number, applicant_id, form_version, form_nickname, funding_year, status,
        certified_at, last_modified_at, allowable_contract_date, number_of_eligible_entities,
        contact_name, contact_email, contact_phone, consulting_firm_data,
        category_one_description, category_two_description)
    values (
        %(application_number)s, %(applicant_id)s, %(form_version)s, %(form_nickname)s, %(funding_year)s,
        %(status)s, %(certified_at)s, %(last_modified_at)s, %(allowable_contract_date)s,
        %(number_of_eligible_entities)s, %(contact_name)s, %(contact_email)s, %(contact_phone)s,
        %(consulting_firm_data)s, %(category_one_description)s, %(category_two_description)s)
    on conflict (application_number) do nothing
"""

INSERT_SERVICE_REQUEST = """
    insert into service_requests (
        application_id, usac_line_number, service_category, service_type, function, quantity, unit,
        manufacturer, other_manufacturer, minimum_capacity, maximum_capacity, installation_initial,
        rfp_attachment_count)
    values (
        %(application_id)s, %(usac_line_number)s, %(service_category)s, %(service_type)s, %(function)s,
        %(quantity)s, %(unit)s, %(manufacturer)s, %(other_manufacturer)s, %(minimum_capacity)s,
        %(maximum_capacity)s, %(installation_initial)s, %(rfp_attachment_count)s)
    on conflict (application_id, usac_line_number) do nothing
"""

INSERT_RFP_DOCUMENT = """
    insert into rfp_documents (service_request_id, url, uploaded_at)
    values (%(service_request_id)s, %(url)s, %(uploaded_at)s)
    on conflict (service_request_id, url) do nothing
"""


def count_rows(cur):
    """Row count per table. Table names come from our fixed list and are quoted with sql.Identifier."""
    counts = {}
    for table in TABLES:
        cur.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table)))
        counts[table] = cur.fetchone()[0]
    return counts


def attach_ids(rows, id_lookup, key_fields, id_field, label):
    """Add each parent's database ID to its child rows. Rows whose parent is missing are skipped."""
    ready = []
    for row in rows:
        key = tuple(row[f] for f in key_fields)
        parent_id = id_lookup.get(key if len(key) > 1 else key[0])
        if parent_id is None:
            log.warning("[%s] no parent row for %s; skipping", label, key)
            continue
        ready.append({**row, id_field: parent_id})
    return ready


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Load raw Form 470 JSON into the database.")
    parser.add_argument("--run", type=Path, help="Run folder under data/raw/ (default: newest complete run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")

    run_dir = args.run or newest_complete_run()
    if run_dir is None or not (run_dir / "summary.json").exists():
        log.error("No complete run folder found. Run python ingest/fetch.py first, or pass --run.")
        return 1
    log.info("Loading run: %s", run_dir.name)

    # --- Read and reshape (no database yet) ---
    service_rows = read_pages(run_dir / "service_requests")
    kept_rows = keep_preferred_version(service_rows)
    applicants = build_applicants(read_pages(run_dir / "applicants"))
    applications = build_applications(kept_rows)
    service_requests = build_service_requests(kept_rows)
    rfp_documents = build_rfp_documents(kept_rows)
    log.info(
        "Read %d API rows -> %d applicants, %d applications, %d service requests, %d RFP documents",
        len(service_rows), len(applicants), len(applications), len(service_requests), len(rfp_documents),
    )

    # --- Connect (the URL holds the password, so it is never printed) ---
    load_dotenv(PROJECT_ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set in .env.")
        return 1

    try:
        # One transaction: "with connect(...)" commits at the end, or rolls everything back on an error.
        with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
            before = count_rows(cur)

            # 1. applicants (no parent)
            cur.executemany(INSERT_APPLICANT, applicants)
            cur.execute("select billed_entity_number, applicant_id from applicants")
            applicant_ids = dict(cur.fetchall())

            # 2. applications -> applicants
            cur.executemany(
                INSERT_APPLICATION,
                attach_ids(applications, applicant_ids, ["billed_entity_number"], "applicant_id", "applications"),
            )
            cur.execute("select application_number, application_id from applications")
            application_ids = dict(cur.fetchall())

            # 3. service_requests -> applications
            cur.executemany(
                INSERT_SERVICE_REQUEST,
                attach_ids(service_requests, application_ids, ["application_number"], "application_id",
                           "service_requests"),
            )
            cur.execute(
                """select a.application_number, sr.usac_line_number, sr.service_request_id
                   from service_requests sr join applications a on a.application_id = sr.application_id"""
            )
            request_ids = {(app, line): sr_id for app, line, sr_id in cur.fetchall()}

            # 4. rfp_documents -> service_requests
            cur.executemany(
                INSERT_RFP_DOCUMENT,
                attach_ids(rfp_documents, request_ids, ["application_number", "usac_line_number"],
                           "service_request_id", "rfp_documents"),
            )

            after = count_rows(cur)
    except psycopg.errors.IntegrityError as error:
        # A row broke a constraint. Report which one, but not the row (it can contain contact details).
        log.error("Load rolled back: %s (constraint: %s, table: %s)",
                  error.diag.message_primary, error.diag.constraint_name, error.diag.table_name)
        return 1
    except psycopg.OperationalError as error:
        log.error("Could not connect or lost the connection: %s", str(error).strip().splitlines()[0])
        return 1

    log.info("---------------- SUMMARY ----------------")
    log.info("%-18s %8s %8s %8s", "table", "before", "after", "added")
    for table in TABLES:
        log.info("%-18s %8d %8d %8d", table, before[table], after[table], after[table] - before[table])
    if after["service_requests"] < 500:
        log.warning("Fewer than 500 service requests loaded (the assignment minimum).")
    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
