"""Data-quality and fairness checks for one raw Form 470 pull.

Usage:
    python scripts/data_quality_check.py                         # newest run in data/raw/
    python scripts/data_quality_check.py data/raw/20261031T194518Z

Reads the raw JSON pages written by ingest/fetch.py, prints a Markdown report,
and saves the same numbers to <run>/quality_report.json (data/raw is Git-ignored).
Standard library only. Read-only: it never changes the raw files.
"""

from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

FIT_FIELDS = ["function", "quantity", "unit", "manufacturer", "rfp_documents"]
SMALL_GROUP = 10  # groups with fewer applications than this get a small-sample warning


def load(run: Path) -> tuple[list[dict], list[dict], dict]:
    rows = [r for f in sorted(glob.glob(str(run / "service_requests" / "*.json"))) for r in json.load(open(f))]
    applicants = [r for f in sorted(glob.glob(str(run / "applicants" / "*.json"))) for r in json.load(open(f))]
    summary = json.load(open(run / "summary.json"))
    return rows, applicants, summary


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        return None


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def size_band(n: str | None) -> str:
    try:
        k = int(float(n))
    except (TypeError, ValueError):
        return "unknown"
    return "1 entity" if k <= 1 else "2-5 entities" if k <= 5 else "6+ entities"


def main() -> int:
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(sorted(glob.glob("data/raw/*/"))[-1])
    rows, applicants, summary = load(run)
    pull_time = datetime.strptime(run.name.rstrip("/"), "%Y%m%dT%H%M%SZ")
    out: dict = {"run": run.name, "filter": summary.get("filter"), "rows": len(rows)}
    p: list[str] = [f"# Data-quality report: run `{run.name}`", "", f"Filter: `{summary.get('filter')}`", ""]

    apps: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        apps[r["application_number"]].append(r)
    n_rows, n_apps = len(rows), len(apps)
    p += [f"Rows: **{n_rows}** · Applications: **{n_apps}** · Applicants (BEN): "
          f"**{len({r['billed_entity_number'] for r in rows})}**", ""]

    # ---------- 1. Completeness ----------
    keys = sorted({k for r in rows for k in r})
    missing = {k: sum(1 for r in rows if k not in r or r[k] in ("", None)) for k in keys}
    out["missing"] = {k: v for k, v in missing.items() if v}
    p += ["## 1. Completeness (fields missing on at least one row)", "", "| Field | Missing rows | % |", "|---|---|---|"]
    p += [f"| `{k}` | {v} | {pct(v, n_rows)} |" for k, v in sorted(out["missing"].items(), key=lambda x: -x[1])]

    # ---------- 2. Validity ----------
    bad_qty = [r.get("quantity") for r in rows if r.get("quantity") and not re.fullmatch(r"\d+(\.\d+)?", r["quantity"])]
    bad_zip = [r for r in rows if not re.fullmatch(r"\d{5}", r.get("billed_entity_zip", ""))]
    bad_email = [r for r in rows if r.get("contact_email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", r["contact_email"])]
    acd_mismatch = []
    for r in rows:
        c, a = parse_dt(r.get("certified_date_time")), parse_dt(r.get("allowable_contract_date"))
        if c and a and a.date() != (c + timedelta(days=28)).date():
            acd_mismatch.append((r["application_number"], (a.date() - c.date()).days))
    acd_apps = sorted({x[0] for x in acd_mismatch})
    out["validity"] = {"non_numeric_quantity": len(bad_qty), "bad_zip": len(bad_zip), "bad_email": len(bad_email),
                       "allowable_date_not_cert_plus_28_rows": len(acd_mismatch),
                       "allowable_date_not_cert_plus_28_apps": len(acd_apps),
                       "gap_days_seen": sorted({x[1] for x in acd_mismatch})}
    p += ["", "## 2. Validity", "",
          f"- `quantity` values that are not plain numbers: **{len(bad_qty)}** (examples: {sorted(set(bad_qty))[:5]})",
          f"- `billed_entity_zip` not 5 digits: **{len(bad_zip)}**",
          f"- `contact_email` not shaped like an email: **{len(bad_email)}**",
          f"- `allowable_contract_date` not equal to certification + 28 days: **{len(acd_mismatch)} rows in "
          f"{len(acd_apps)} applications** (day gaps seen: {out['validity']['gap_days_seen'][:10]})",
          f"- Status values: {dict(Counter(r.get('fcc_form_470_status') for r in rows))}"]

    # ---------- 3. Uniqueness ----------
    def key(r: dict) -> tuple:
        return (r["application_number"], r["form_version"], r.get("service_request_id"),
                (r.get("rfp_documents") or {}).get("url"))
    dup_keys = sum(c - 1 for c in Counter(key(r) for r in rows).values() if c > 1)
    exact_dups = n_rows - len({json.dumps(r, sort_keys=True) for r in rows})
    per_app = sorted(len(v) for v in apps.values())
    out["uniqueness"] = {"duplicate_composite_keys": dup_keys, "exact_duplicate_rows": exact_dups,
                         "rows_per_app_min": per_app[0], "rows_per_app_median": per_app[len(per_app) // 2],
                         "rows_per_app_max": per_app[-1]}
    p += ["", "## 3. Uniqueness", "",
          f"- Duplicate (application, version, request id, RFP url) keys: **{dup_keys}**",
          f"- Exact duplicate rows: **{exact_dups}**",
          f"- Rows per application: min {per_app[0]}, median {per_app[len(per_app)//2]}, max {per_app[-1]}"]

    # ---------- 4. Consistency ----------
    ben_names: dict[str, set] = defaultdict(set)
    for r in rows:
        ben_names[r["billed_entity_number"]].add(r["billed_entity_name"])
    multi_name = {b: n for b, n in ben_names.items() if len(n) > 1}
    emp_eq_name = sum(1 for r in rows if r.get("authorized_person_employer")
                      and r.get("authorized_person_employer") == r.get("authorized_person_name"))
    app_versions = Counter(tuple(sorted({r["form_version"] for r in v})) for v in apps.values())
    # declared attachment count vs actual distinct RFP urls per service request
    req: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        req[(r["application_number"], r["form_version"], r.get("service_request_id"))].append(r)
    att_mismatch = 0
    for v in req.values():
        declared = v[0].get("service_request_rfp_attachment")
        actual = len({(r.get("rfp_documents") or {}).get("url") for r in v if r.get("rfp_documents")})
        if declared is not None and int(float(declared)) != actual:
            att_mismatch += 1
    out["consistency"] = {"bens_with_multiple_names": len(multi_name), "employer_equals_person_rows": emp_eq_name,
                          "versions_per_application": {"+".join(k): c for k, c in app_versions.items()},
                          "requests_where_declared_attachments_differ": att_mismatch, "service_requests": len(req)}
    p += ["", "## 4. Consistency", "",
          f"- BENs with more than one name: **{len(multi_name)}**",
          f"- Rows where `authorized_person_employer` equals `authorized_person_name`: **{emp_eq_name}** of {n_rows}",
          f"- Form versions per application: {out['consistency']['versions_per_application']}",
          f"- Service requests whose declared attachment count differs from RFP rows present: "
          f"**{att_mismatch}** of {len(req)}"]

    # ---------- 5. Timeliness ----------
    last_mod = max(parse_dt(r["last_modified_date_time"]) for r in rows)
    past = {a for a, v in apps.items() if (d := parse_dt(v[0].get("allowable_contract_date"))) and d < pull_time}
    out["timeliness"] = {"newest_last_modified": last_mod.isoformat(), "pull_time_utc": pull_time.isoformat(),
                         "apps_allowable_date_already_passed": len(past)}
    p += ["", "## 5. Timeliness", "",
          f"- Pulled {pull_time:%Y-%m-%d %H:%M} UTC; newest `last_modified_date_time` {last_mod}",
          f"- Applications whose `allowable_contract_date` had already passed at pull time: **{len(past)}** of {n_apps} "
          f"({pct(len(past), n_apps)})"]

    # ---------- 6. Fairness ----------
    def group_of(v: list[dict], dim: str) -> str:
        r = v[0]
        if dim == "applicant_type":
            return r.get("applicant_type", "unknown")
        if dim == "consultant":
            return "uses consultant" if r.get("consulting_firm_data") else "no consultant"
        if dim == "size":
            return size_band(r.get("number_of_eligible_entities"))
        return r.get("billed_entity_state", "unknown")

    p += ["", "## 6. Fairness check", "",
          "Question: would a ranking or filter built on this data treat some kinds of applicants worse for reasons "
          "unrelated to how well they fit my business? Groups: applicant type, size (eligible entities), "
          f"consultant use, and state. Groups with fewer than {SMALL_GROUP} applications are marked (small n).", ""]
    out["fairness"] = {}
    current_only = {a for a, v in apps.items() if any(r["form_version"] == "Current" for r in v)}
    certified = {a for a, v in apps.items() if v[0].get("fcc_form_470_status") == "Certified"}
    for dim in ["applicant_type", "size", "consultant", "state"]:
        g: dict[str, dict] = defaultdict(lambda: {"apps": 0, "rows": 0, "fit_missing": 0, "fit_cells": 0,
                                                    "kept_current_only": 0, "kept_open_bids": 0})
        for a, v in apps.items():
            s = g[group_of(v, dim)]
            s["apps"] += 1
            s["rows"] += len(v)
            for r in v:
                for f in FIT_FIELDS:
                    s["fit_cells"] += 1
                    s["fit_missing"] += f not in r or r[f] in ("", None)
            s["kept_current_only"] += a in current_only
            s["kept_open_bids"] += a not in past and a in certified
        out["fairness"][dim] = g
        p += [f"### By {dim.replace('_', ' ')}", "",
              "| Group | Apps | % of apps | % of rows | Rows/app | Fit fields missing | Kept by Current-only filter "
              "| Kept by open-bids filter |", "|---|---|---|---|---|---|---|---|"]
        for name, s in sorted(g.items(), key=lambda x: -x[1]["apps"]):
            flag = " (small n)" if s["apps"] < SMALL_GROUP else ""
            p.append(f"| {name}{flag} | {s['apps']} | {pct(s['apps'], n_apps)} | {pct(s['rows'], n_rows)} | "
                     f"{s['rows'] / s['apps']:.1f} | {pct(s['fit_missing'], s['fit_cells'])} | "
                     f"{s['kept_current_only']} ({pct(s['kept_current_only'], s['apps'])}) | "
                     f"{s['kept_open_bids']} ({pct(s['kept_open_bids'], s['apps'])}) |")
        p.append("")
    p += ["Columns: *% of rows vs % of apps* shows over- or under-weighting if anything counts rows. "
          f"*Fit fields missing* = share of empty cells across {FIT_FIELDS}. *Current-only* keeps applications "
          "with a `Current` version. *Open-bids* keeps certified applications whose allowable contract date "
          "had not passed at pull time."]

    print("\n".join(p))
    (run / "quality_report.json").write_text(json.dumps(out, indent=2, default=dict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
