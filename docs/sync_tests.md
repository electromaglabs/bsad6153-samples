# Sync tests: breaking it on purpose (Milestone 3, Part G)

Each test below shows what I did, what I predicted, what happened, and the resulting `sync_runs` row.
Times are US Central unless marked UTC.

| Test | Date | Result |
|---|---|---|
| Rerun (twice back to back) | 2026-11-17 | Passed: second run inserted 0, updated 0, deleted 0 |
| Bad credentials (invalid Socrata app token) | 2026-11-22 | Passed: run failed cleanly, no data written, exit code 1 |
| Golden-question check | 2026-11-22 (baseline) | Baseline saved; second check after two more scheduled syncs |

## Test 1: Rerun

**What I did.** Ran `python ingest/sync.py` twice in a row on 2026-11-17, before the schedule existed.

**Prediction.** Run 1 has no watermark yet, so it re-checks everything: it should insert only forms filed
since the Milestone 2 load (2026-11-11) and update only forms changed at USAC since then. Run 2 should
fetch only the 7-day overlap window and insert 0, update 0.

**What happened.**

```
22:09:03 INFO    ---------------- SUMMARY (run #1: success) ----------------
22:09:03 INFO    table               inserted   updated   deleted
22:09:03 INFO    applicants                 4         0         0
22:09:03 INFO    applications              29         8         0
22:09:03 INFO    service_requests         231        50         0
22:09:03 INFO    rfp_documents            525         0         0
22:09:03 INFO    API rows fetched: 13932. New watermark: 2026-11-16 17:52:23-05:00

22:10:16 INFO    ---------------- SUMMARY (run #2: success) ----------------
22:10:16 INFO    table               inserted   updated   deleted
22:10:16 INFO    applicants                 0         0         0
22:10:16 INFO    applications               0         0         0
22:10:16 INFO    service_requests           0         0         0
22:10:16 INFO    rfp_documents              0         0         0
22:10:16 INFO    API rows fetched: 720. New watermark: 2026-11-16 22:52:23+00:00
```

**Resulting `sync_runs` rows.** Run #1: success, manual, 13,932 fetched, 789 inserted, 58 updated.
Run #2: success, manual, 720 fetched, 0 inserted, 0 updated, 0 deleted.

**Checks.**
- Run 1 updated 50 service requests but only 8 applications. A query for line items updated without their
  application also changing returned **0**, so every line-item update came with an amended form at USAC.
- Run 2 fetched 720 rows (the 7-day overlap) and changed nothing. The `is distinct from` condition in the
  upsert is what keeps unchanged rows from being "updated".
- The two watermarks are the same moment: 17:52:23 Eastern is 22:52:23 UTC. Run 2 printed the value as the
  database returned it, in UTC.

## Test 2: Bad credentials

**What I did.** Ran one sync with an invalid Socrata app token, set for that command only, so `.env`
stayed unchanged (`load_dotenv()` never overrides a variable that is already set):

```bash
SOCRATA_APP_TOKEN=not-a-real-token python ingest/sync.py
echo $?
```

**Prediction.** USAC rejects the token, the run is recorded as `failed` with a readable error, no data is
written, the watermark stays where it was, and the exit code is 1 (a red X in GitHub Actions).

**What happened.**

```
16:47:37 INFO    Started sync run #13 (trigger: manual)
16:47:37 INFO    Watermark: 2026-11-20 21:59:43+00:00. Fetching changes since: 2026-11-13 21:59:43+00:00
16:47:38 ERROR   HTTP 403 - not retrying. Response: {
  "code" : "permission_denied",
  "error" : true,
  "message" : "Invalid app_token specified"
}

16:47:38 ERROR   Sync failed: FetchError: USAC request failed at offset 0 after retries
$ echo $?
1
```

**Resulting `sync_runs` rows.**

| run_id | status  | trigger  | records_fetched | records_inserted | watermark              | error_message                                             |
|---|---|---|---|---|---|---|
| 13     | failed  | manual   | 0               | 0                | 2026-11-20 21:59:43+00 | FetchError: USAC request failed at offset 0 after retries |
| 12     | success | schedule | 994             | 220              | 2026-11-20 21:59:43+00 | null                                                      |

**Checks.**
- The 403 was not retried, which is correct: a bad key is the request's fault, and retrying cannot fix
  it. Only temporary problems are retried with backoff: timeouts, dropped connections, 429 (rate limited)
  and 5xx (server trouble).
- Nothing was written: the failure happened during the fetch, before the data transaction began.
- The watermark is unchanged (it is read only from successful or partial runs), so the next good run picks
  up exactly where run #12 left off.
- The token itself appears nowhere in the log or the `error_message`.

**Fix that came out of this test.** The message said "after retries", but a 403 is never retried. I changed
it to "USAC request failed at offset 0 (see the log for the HTTP status)". Run #13 keeps the old wording
because it ran before the fix.

## Golden-question check

**What I did.** Ran `python evals/check_reference.py` as soon as the question set was written. It runs
every reference query as `app_reader` in a read-only transaction and saves a fingerprint (short hash) of
each answer, so a later run can show which answers changed.

**Baseline:** `evals/results/reference_20261122T224034Z.csv` (2026-11-22 22:40 UTC, after scheduled run #12).
All 12 SQL questions ran and returned rows; the 5 should_decline questions have no SQL and were skipped.

| id | rows (baseline) |
|---|---|
| Q01 | 143 |
| Q02 | 15 |
| Q03 | 34 |
| Q04 | 9 |
| Q05 | 24 |
| Q06 | 156 |
| Q07 | 119 |
| Q08 | 88 |
| Q14 | 4 |
| Q15 | 1 |
| Q16 | 1 |
| Q17 | 69 |

**Second check:** to be run after at least two more scheduled syncs (the next two are due 2026-11-22
5:43 PM and 2026-11-23 5:43 AM; GitHub has been starting them up to 8 hours late). Results go here: which
answers changed, and confirmation that every query still runs.
