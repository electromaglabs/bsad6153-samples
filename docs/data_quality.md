# Data Quality and Fairness Check: E-Rate FCC Form 470

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
