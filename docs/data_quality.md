# Data Quality and Fairness Check: E-Rate FCC Form 470

> **Two parts.** [Milestone 3](#milestone-3-the-live-database-measured-2026-11-22) measures the synced database
> with SQL. The Milestone 2 sections below it measured one raw API pull before the database existed and are kept
> as a record of that earlier snapshot.

<!-- Numbers below come from scripts/data_quality_check.py run on 2026-11-08 against
     run 20261031T194518Z (filter billed_entity_state in('OK','KS') AND funding_year in('2027'), 1,457 rows).
     Re-run the script before changing any number in this file. -->

## What was checked and how

| | |
|---|---|
| **Test data** | One raw pull, `data/raw/20261031T194518Z/` (Git-ignored): 1,457 service-request rows, 129 applications, 119 applicants (BENs), Oklahoma and Kansas, funding year 2027 |
| **Script** | [`scripts/data_quality_check.py`](../scripts/data_quality_check.py), standard library only, read-only |
| **Run it** | `python scripts/data_quality_check.py data/raw/20261031T194518Z` (prints a report; saves `quality_report.json` in the run folder) |
| **Checks** | Completeness, validity, uniqueness, consistency, timeliness, and a fairness check across groups of applicants |

The question behind every check: **if my agent ranked and filtered Form 470s from this data, where would it go wrong, and who would it miss?**

## Summary of findings

| # | Finding | Dimension | Severity | What the system will do |
|---|---|---|---|---|
| 1 | Filtering to `form_version = Current` drops **every** library, school, and no-consultant application | Fairness | High | Never filter by version. Keep one row per application: `Current` if it exists, otherwise `Original` |
| 2 | Counting rows overweights large, consultant-filed school districts | Fairness | High | Count and rank at the **application** level (Week 2 `application` table), never by rows |
| 3 | `manufacturer` is always empty on Category 1 (internet) lines, which most library requests are | Fairness / completeness | Medium | Treat `manufacturer` as "not applicable" for Category 1; don't score how complete a form is |
| 4 | 51 of 129 applications (39.5%) had passed their `allowable_contract_date` at pull time | Timeliness | High | Agent only drafts outreach for certified forms whose date is still in the future; deadline shown on every draft |
| 5 | 5 applications have an allowable contract date 35-45 days after certification, not 28 | Validity | Medium | Store the date from USAC; never compute it from certification + 28 |
| 6 | `authorized_person_employer` equals `authorized_person_name` on all 1,457 rows | Consistency | Low | Don't use the employer field; use `billed_entity_name` |
| 7 | 4 canceled forms are missing service fields entirely (keys absent, not null) | Completeness | Medium | Exclude `Canceled` status; read every optional field with `.get()` |

## 1. Completeness

Socrata leaves a key out of the JSON when the value is empty, so "missing" means the key isn't there. Fields that matter for ranking a lead:

| Field | Missing rows (of 1,457) | Note |
|---|---|---|
| `manufacturer` | 301 (20.7%) | Missing on all 168 Category 1 rows by design (see Finding 3) |
| `quantity` / `unit` | 140 (9.6%) | |
| `rfp_documents` | 42 (2.9%) | No attachment to read for those requests |
| `consulting_firm_data` | 20 (1.4%) | These 20 rows are the 11 applications filed without a consultant |
| `service_type`, `service_category`, `function`, `service_request_id` | 4 (0.3%) | The 4 canceled forms |
| `technical_contact_*` | 1,330 (91.3%) | Usually blank; `contact_*` is always filled, so outreach uses that |

## 2. Validity

- `quantity` arrives as text but every value present is a plain number (0 bad values). Convert it on load.
- ZIP codes are all 5 digits; all contact emails are shaped like emails.
- **`allowable_contract_date` is not always certification + 28 days.** 176 rows in 5 applications show gaps of 35, 36, 37, 38, and 45 days. My data dictionary's "certification + 28" rule is wrong for these, so the deadline must come from USAC's field.
- Status values: `Certified` (1,453 rows), `Canceled` (4 rows).

## 3. Uniqueness

- The key (`application_number`, `form_version`, `service_request_id`, `rfp_documents.url`) had **0 duplicates**, and there were 0 exact duplicate rows.
- Rows per application: minimum 1, median 4, maximum 98. One row is one request line **times** one RFP attachment, so row counts measure paperwork, not demand.

## 4. Consistency

- Each BEN has exactly one name (0 conflicts).
- `authorized_person_employer` equals `authorized_person_name` on **all 1,457 rows**. This settles Surprise #3 in the data dictionary: it's a dataset-wide field problem, not a one-off error.
- Versions per application: 90 `Original` only, 37 `Current` only, 2 both. Most forms are never re-processed, so `Original` is often the only version.
- Declared attachment count (`service_request_rfp_attachment`) matched the RFP rows present for 512 of 513 service requests.

## 5. Timeliness

- Pulled 2026-10-31 19:45 UTC; newest `last_modified_date_time` was 2026-10-30 18:23. The data was one day old.
- **51 of 129 applications (39.5%) had already passed their `allowable_contract_date`.** Without a date filter, more than a third of the agent's leads would be closed bids, which is the "contacting schools about expired contracts" harm named in my ethics check.

## 6. Fairness check

### Design

**Question:** Would a ranking or filter built on this data treat some kinds of applicants worse for reasons that have nothing to do with how well they fit my business?

**Who could be treated unfairly:** Small and rural applicants, libraries, and applicants who file without a paid E-Rate consultant. They are often the ones with the least IT staff, so they are real prospects for an MSP, and they're easy to lose.

**Groups compared:** applicant type, size (`number_of_eligible_entities`: 1, 2-5, 6+), consultant use (`consulting_firm_data` present or not), and state.

**Measures, per group:**
1. **Weighting:** share of applications vs. share of rows. If anything counts rows, a group whose row share is higher than its application share is overweighted.
2. **Missing fit fields:** share of empty cells across `function`, `quantity`, `unit`, `manufacturer`, `rfp_documents`.
3. **Filter survival:** share of each group's applications kept by two filters the agent would likely use: *Current-only* (`form_version = Current`) and *open bids* (certified, allowable contract date not yet passed).

**Decision rule:** a group is flagged if its survival under a filter is 20 or more percentage points below the overall rate, or its row share is more than 1.25 times its application share (or less than 0.8 times). Groups under 10 applications are reported but marked as small samples.

### Results

**By applicant type** (overall: Current-only keeps 39 of 129 = 30.2%; open bids keeps 78 of 129 = 60.5%)

| Group | Apps | % of apps | % of rows | Rows/app | Fit fields missing | Kept by Current-only | Kept by open bids |
|---|---|---|---|---|---|---|---|
| School District | 110 | 85.3% | 96.7% | 12.8 | 8.0% | 38 (34.5%) | 68 (61.8%) |
| Library | 10 | 7.8% | 1.5% | 2.2 | 36.4% | **0 (0%)** | 5 (50.0%) |
| School (small n) | 6 | 4.7% | 1.0% | 2.3 | 20.0% | **0 (0%)** | 3 (50.0%) |
| Consortium (small n) | 2 | 1.6% | 0.5% | 3.5 | 31.4% | 1 (50.0%) | 1 (50.0%) |
| Library System (small n) | 1 | 0.8% | 0.3% | 5.0 | 0.0% | 0 (0%) | 1 (100%) |

**By consultant use**

| Group | Apps | % of apps | % of rows | Rows/app | Fit fields missing | Kept by Current-only | Kept by open bids |
|---|---|---|---|---|---|---|---|
| Uses consultant | 118 | 91.5% | 98.6% | 12.2 | 8.3% | 39 (33.1%) | 70 (59.3%) |
| No consultant | 11 | 8.5% | 1.4% | 1.8 | 29.0% | **0 (0%)** | 8 (72.7%) |

**By size**

| Group | Apps | % of apps | % of rows | Rows/app | Fit fields missing | Kept by Current-only | Kept by open bids |
|---|---|---|---|---|---|---|---|
| 1 entity | 33 | 25.6% | 20.6% | 9.1 | 11.3% | 9 (27.3%) | 16 (48.5%) |
| 2-5 entities | 51 | 39.5% | 29.9% | 8.5 | 9.5% | 10 (19.6%) | 38 (74.5%) |
| 6+ entities | 45 | 34.9% | 49.5% | 16.0 | 6.9% | 20 (44.4%) | 24 (53.3%) |

**By state**

| Group | Apps | % of apps | % of rows | Rows/app | Fit fields missing | Kept by Current-only | Kept by open bids |
|---|---|---|---|---|---|---|---|
| OK | 103 | 79.8% | 86.4% | 12.2 | 8.9% | 35 (34.0%) | 57 (55.3%) |
| KS | 26 | 20.2% | 13.6% | 7.6 | 7.0% | 4 (15.4%) | 21 (80.8%) |

### What the results mean

**Finding 1: the Current-only filter is the biggest risk.** Libraries, schools, and no-consultant applicants keep 0% under it, against 30.2% overall. "Use the latest version" sounds like harmless cleanup, but `Current` only exists when USAC has re-processed a form, which happens mostly to large, consultant-filed district applications. **If my agent applied this filter without knowing this, every library and every self-filed applicant would disappear from my leads, and nothing in the output would show it.** These are often the applicants with the least IT staff, which makes them some of my best prospects. Kansas (15.4%) and 2-5-entity applicants (19.6%) also lose more than average, but stay under the 20-point flag.

**Finding 2: row counts overweight big districts.** Districts have 85.3% of applications but 96.7% of rows; consultant-filed applications have 91.5% of applications but 98.6% of rows; 6+-entity applicants have 34.9% of applications but 49.5% of rows. Flagged by the ratio rule: 6+-entity applicants (1.42) are overweighted; libraries (0.19), schools (0.21), and no-consultant applicants (0.16) are heavily underweighted. Districts as a group (1.13) fall just under the flag. Any "most active" or "most requested" ranking built on rows rewards paperwork, not need.

**Finding 3: the missing-field gap is partly structural.** Libraries look like they have sloppy forms (36.4% of fit fields missing vs. 8.0% for districts), but 18 of 22 library rows are Category 1 internet requests, and `manufacturer` is empty on every Category 1 row by design. Within Category 1 alone, libraries are still missing more (40.0% vs. 23.3% for districts), but on only 18 rows. The risk isn't bad library data. It's a fit score that rewards complete-looking forms and so ranks internet requests, which are mostly libraries, below hardware requests.

**Open bids filter:** no group is flagged (libraries and 1-entity applicants are 10-12 points below overall). This filter is needed for Finding 4 and doesn't introduce a fairness problem in this pull.

### Fixes, and how I'll know they work

- Deduplicate versions per application (prefer `Current`, fall back to `Original`) instead of filtering. Check: every group's survival after dedup should be 100% of its applications.
- Build the Week 2 `application` table and rank from it, one row per application.
- Score fit from `service_type` and `function` (what's requested), not from how many fields are filled in.
- Re-run `scripts/data_quality_check.py` after each larger sync (more states or years) and in Week 3 `sync_tests.md`, so the per-group survival table is checked whenever the data changes.

## Limits of this check

- **One snapshot:** one pull, two states, one funding year, early in the FY2027 filing window. Rates will change as more forms are certified.
- **Small groups:** libraries (10), schools (6), consortia (2), and library systems (1) are small. The 0% results are exact counts for this pull, not stable rates.
- **Proxies:** `number_of_eligible_entities` stands in for applicant size, and I have no rural/urban field. Distance from Alva, which the agent will use, could add its own bias (for example, against western Kansas) and is not tested here.
- **No outcome data:** I can't measure whether rankings are *correct* yet, only whether the data and filters treat groups evenly. That's a Week 5-7 evaluation question.

---

# Milestone 3: the live database, measured 2026-11-22

Every number below comes from a query in [`db/quality_checks.sql`](../db/quality_checks.sql), run as `app_reader`
with `python scripts/run_quality_checks.py` on **2026-11-22**, after scheduled sync run #12. The check name in
brackets, such as [check 1], points to the query. The data changes every sync, so re-run the script before
quoting any number.

## Row counts [check 1]

| Table | Rows (2026-11-22) |
|---|---|
| applicants | 807 |
| applications | 1,279 |
| service_requests | 6,314 |
| rfp_documents | 13,538 |
| sync_runs | 14 |

Since the Milestone 2 load on 2026-11-11 (797 applicants, 1,217 applications, 5,929 service requests), the sync has
added 10 applicants, 62 applications and 385 service requests.

## Null rates [checks 2a-2c]

| Field | Missing (2026-11-22) | What it means |
|---|---|---|
| `applications.consulting_firm_data` | 12.7% of 1,279 | Filed without a consultant. A real answer, not missing data: these are the schools I can contact directly (golden question Q08) |
| `applications.form_nickname` | 0.0% | Always present |
| `applications.category_one_description` | 56.0% | Most forms request only Category 2, so they have nothing to describe for Category 1 |
| `applications.category_two_description` | 37.1% | Forms that request only Category 1 (internet) |
| `applicants.address_1`, `applicants.phone` | 0.0% of 807 | Always present |
| `service_requests.quantity` / `unit`, Category 1 | 6.4% of 1,054 | Left blank on the form; not yet checked which kinds of lines these are |
| `service_requests.quantity` / `unit`, Category 2 | 9.9% of 5,260 | Left blank on the form; not yet checked which kinds of lines these are |
| `service_requests.manufacturer`, Category 1 | 100.0% | USAC never asks for a brand on internet service (Milestone 2, Finding 3) |
| `service_requests.manufacturer`, Category 2 | 10.4% | Some equipment lines leave the brand blank |
| `service_requests.minimum_capacity`, Category 2 | 100.0% | Capacity applies only to internet service |

## Duplicates [checks 3a-3c]

- **By natural ID: 0 in every table** (2026-11-22). The UNIQUE constraints make duplicates impossible, and the
  upsert updates the existing row instead of inserting a second one. The rerun test in
  [`sync_tests.md`](sync_tests.md) confirms it from the other direction.
- **Same applicant under two BENs: 0** (2026-11-22). No two applicants share a name and city.
- **Same form filed twice: 10 applicants** (2026-11-22) filed two applications with the same nickname in the same
  funding year. Seven are a canceled form plus its certified replacement, one is two canceled forms, and two
  (Coleman, Woodward) are two certified forms each.

## Out-of-range and inconsistent values [check 4]

| Check | Rows (2026-11-22) |
|---|---|
| Certified in the future | 0 |
| Funding year outside 2026-2027 | 0 |
| Bidding window shorter than 28 days | 0 (also blocked by a CHECK constraint) |
| Quantity of 0 | 3 |
| Unit given without a quantity | 4 |
| Category 1 line naming a manufacturer | 0 |
| Canceled form with line items | 0 |
| USAC's attachment count higher than the attachments it lists | 33 |

Time zones: USAC sends times without a zone. The sync treats them as US Eastern and stores them as `timestamptz`,
so no mixed time zones can be stored.

The 33 attachment mismatches are in the source, not the sync. In the raw API data for those 33 line items,
`service_request_rfp_attachment` says (for example) 3 documents, but the rows list only 2 URLs, with no repeated
URLs. USAC's count is simply higher than the documents it publishes.

## Orphans [check 5]

| Check | Rows (2026-11-22) |
|---|---|
| Service requests without an application | 0 |
| RFP documents without a service request | 0 |
| Certified applications without line items | 0 |
| Canceled applications without line items | 37 |
| Applicants without applications | 0 |

**How the design handles orphans.** Foreign keys make true orphans impossible: a child row can't be inserted
without its parent, and the sync always writes parents first. If a child's parent is missing (for example, its
parent row broke a constraint), the sync logs and skips that child instead of inventing a parent. Deleting a line
item cascades to its RFP documents. The 37 canceled applications with no line items are expected: USAC removes
the service details from a form when it is canceled (Milestone 2, Finding 7).

## Decisions: cleaned, rejected, and left alone

| Decision | What | Why |
|---|---|---|
| **Cleaned** | Times converted from US Eastern (no zone) to `timestamptz` | Comparisons and "days left" are wrong if time zones mix |
| **Cleaned** | One row per application, `Current` version over `Original` | Avoids double-counting a form (Milestone 2, Finding 1) |
| **Cleaned** | API rows split into line items and RFP documents | The API repeats a line item once per attachment |
| **Cleaned** | Line items and documents that disappear from a re-fetched form are deleted | A plain upsert would keep stale lines after a school amends its form |
| **Rejected** | Rows that break a constraint are skipped, and the run is marked `partial` | Bad rows never reach the tables; 0 so far (every run has been `success`) |
| **Left alone** | The 3 zero quantities and 4 units without a quantity | They are what the school filed; changing them would misstate the request |
| **Left alone** | The 33 attachment counts higher than the listed documents | Store USAC's count and the documents that exist. Never fill in missing documents; the chatbot must not claim it has every RFP document for those lines |
| **Left alone** | The 10 same-nickname pairs | USAC treats them as separate filings with separate numbers and deadlines. Counting questions should use certified applications only, which drops the canceled half of 7 pairs |
| **Left alone** | Missing consultant, category descriptions, manufacturers | Each blank has a meaning (see the null-rate table), so it is not filled with a placeholder |

## Fairness check [checks 6a-6d]

**Concrete example: answers about my own area rest on thin evidence.** The near-Alva town list holds
**21 applicants and 36 applications, 2.8% of all 1,279 applications** (2026-11-22). The other 1,243 come from the
rest of Oklahoma and Kansas. If my future chatbot answered "what do schools around Alva usually buy?" or "is
demand rising near Alva?" from this data, it would be generalizing from 36 forms, and a single district's filing
could swing the answer. A statewide pattern, such as "most districts use a consultant", could be wrongly applied
to local schools that behave differently.

A second gap affects judgments about individual schools: **490 of 807 applicants (60.7%) filed only one
application** (2026-11-22). One form says what a school wanted this year, not how it manages technology. That's
why golden question Q13, "which district is worst at managing its technology?", is a should-decline question.

Other measurements, for context (2026-11-22):

| Group | Applicants | Applications |
|---|---|---|
| Oklahoma | 480 | 792 (61.9%) |
| Kansas | 327 | 487 (38.1%) |
| School districts | 629 | 1,043 |
| Libraries | 82 | 101 |
| Schools | 76 | 105 |
| Library systems | 17 | 26 |
| Consortia | 3 | 4 |

Libraries, schools, library systems and consortia together filed 236 applications (18.5%). "Typical applicant"
answers will mostly describe school districts.

**What the system will do about it.** Answers about the Alva area or about a single applicant should give the
number of applications they rest on. Rankings and judgments of applicants should be declined (Q13). The near-Alva
filter stays labeled as a hand-made town list, not a measured drive time (Q05, Q09).

## Change log: what the scheduled runs taught me (Milestone 3)

| Date | Learned | What I did |
|---|---|---|
| 2026-11-17 | All rows of one application share one `last_modified_date_time` (checked across 1,217 applications) | Safe to fetch by watermark and to delete lines that disappear from a re-fetched form |
| 2026-11-17 | USAC lists the dataset's update frequency as daily; rows last updated 2026-11-16 | Chose a 12-hour schedule (README) |
| 2026-11-17 | Supabase had Row Level Security on for every table, so `app_reader` saw 0 rows with no error | Added a read policy per table instead of turning RLS off |
| 2026-11-17 | Schools amend forms: the first sync updated 8 applications and 50 of their line items | The upsert updates only changed rows; lines removed from a form are deleted |
| 2026-11-18 | GitHub started the first scheduled run about 8 hours late (due 11:43 UTC, started 19:34 UTC) | Counted it in the freshness guarantee; later runs were also up to 7 hours late |
| 2026-11-18 | `status.py` reported "0 changed" for a week because all rows were first loaded inside its 7-day window | Expected until the Milestone 2 load is older than 7 days; no change needed |
| 2026-11-22 | The newest USAC change stayed at 2026-11-20 all weekend | USAC may not publish on weekends; added to the freshness guarantee, to confirm next weekend |
| 2026-11-22 | USAC lists fewer RFP documents than its own attachment count on 33 line items | Left as published (see Decisions) |
| 2026-11-22 | An invalid app token gets HTTP 403, which the sync correctly does not retry | Fixed the error message, which wrongly said "after retries" |

**Known gap: whole applications that disappear.** The sync deletes line items and documents that vanish from a
form it re-fetches, but an application deleted from USAC entirely never shows up in an incremental fetch, so it
would stay in my tables. None has been seen so far. A periodic `python ingest/sync.py --full` re-checks every
record, but it does not delete missing applications either; that would need a separate cleanup step.

## Ownership and alerting (Milestone 3)

If this were a company system:

| Role | Who | Responsible for |
|---|---|---|
| **Pipeline owner** | The data engineer who maintains `ingest/` (in my business, me) | Fixing failed runs, rotating the database password and Socrata token, schema changes |
| **Data consumer** | Sales and outreach staff who use the app and chatbot | Reporting answers that look wrong or stale |
| **Source contact** | USAC Open Data support | Problems in the published data, such as the 33 attachment-count gaps |

**Who is alerted, and how:**

- **A failed sync:** the pipeline owner. GitHub emails the repository owner when a workflow fails (red X), and the
  failure is recorded in `sync_runs` with its error message.
- **Stale data:** the people using the data. From Milestone 4, the app shows when data was last updated, and the
  chatbot will warn when the last successful sync is more than 30 hours old (`scripts/status.py`).
- **A partial run:** the pipeline owner. It shows as a warning in the Actions log and in `sync_runs.error_message`,
  listing the skipped applications.

A gap in this setup: GitHub's failure email goes to one person. In a company, failures should also go to a shared
channel, so a sync doesn't go unfixed while the owner is away.
