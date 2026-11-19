# Implementation Brief (v1): E-Rate Lead Finder for MSPs

**Author:** Kalynn Samples · **Version 1:** 2026-11-18 · Revised in the Governance & User Test Review; becomes the Final Business Case in Week 8.

## 1. My workflow

**Decision:** each week I decide which schools, libraries, and districts within about an hour of Alva, Oklahoma (including southern Kansas) my IT and electrical business should reach out to about IT work.

**How I do it today** (from `docs/baseline_log.md`):

| Source | Time | Logged how |
|---|---|---|
| Alva business directory | 18 min | Timed (10-28) |
| Facebook business pages | 17 min | Timed (10-18) |
| Google search | ~26 min | Estimated |
| Free open-data lists | ~38 min | Estimated |
| E-Rate Form 470 data, by hand | Several hours a week | Estimated, spread across the week |

Only two entries were timed live; the rest, including E-Rate, are estimates and are marked that way in the log. The first timed E-Rate session in my usage log (Milestone 4) will give a measured comparison.

**What frustrates me:** none of these sources say what a prospect actually needs. Google ranks paid ads first. Facebook pages don't show whether a business is still active, and contact details and business location can be inaccurate or outdated. E-Rate data is the one source that says exactly what a school wants and when bids close, but sorting it by hand takes hours, so deadlines slip by. My confidence never rose above 3 out of 5.

## 2. Should this use AI?

| Option | What it would solve | Cost | What could go wrong |
|---|---|---|---|
| **A. No new technology:** a set weekly USAC check, a checklist, and a lead spreadsheet | Consistency: no skipped weeks | $0, but still hours of manual work | Still slow; deadlines still missed |
| **B. Data without AI:** saved SQL (`db/queries.sql` Q1–Q5) on a Streamlit page over my synced Supabase database | Open bids with days left, near-Alva filter, equipment demand, consultant vs. direct filers, best months to watch | $0 on free tiers; mostly built already | "Near Alva" is a hand-made town list, not real drive time; data can be up to ~12 h old |
| **C. LLM chatbot and agent** (Milestones 5–6) | Plain-English questions; judging how well a free-text request fits my services; summarizing RFP documents; drafting outreach for my review | ~$8/month estimated (Section 4) | Invented deadlines or requirements; a poorly worded email that hurts my reputation with a district |

**Honest conclusion:** most of the value comes from **Option B**. "Which bids are open, near me, and still before their deadline?" is a filter, and SQL answers it exactly and for free. An LLM is needed only for the fuzzy parts: matching free-text service descriptions to what my business does well, summarizing RFP attachments, and writing a first-draft email. Deadlines, contacts, and eligibility must always come from SQL, never from the model.

## 3. Value hypothesis

1. **Time:** E-Rate lead search takes several hours a week today (estimated). **Target: under 30 minutes a week**, finding the same leads.
2. **Missed opportunities:** in my first pull, 51 of 129 applications (39.5%) were already past their `allowable_contract_date` (`docs/data_quality.md`). **Target: review every in-range Form 470 before its deadline, and make at least one bid or meaningful contact a month.**

**How I'll measure it:** from Milestone 4 I time every session in `docs/usage_log.md` and compare it with the baseline. In the same log I record bids, quotes, and meaningful contacts, which my baseline reflection names as the real proof of value.

## 4. Early cost estimate

| Item | Monthly cost |
|---|---|
| Supabase database (free tier) | $0 |
| GitHub Actions sync, twice a day (public repo) | $0 |
| Render website (free tier; sleeps when idle) | $0 |
| USAC Socrata API (free app token) | $0 |
| Chatbot, Claude Sonnet 5.5 at $2 / $10 per million input / output tokens: 10 questions a day × (~6,000 input + ~800 output tokens) ≈ $0.02 per question | ~$6 |
| Weekly agent: ~20 new forms × (~8,000 input + ~600 output tokens) | ~$2 |
| **Total** | **~$8** |

**Assumptions:** pricing from Anthropic's pricing page, checked 2026-11-18. Question volume is my own use; public visitors can't reach the chatbot without `APP_PASSWORD`. Milestone 5 replaces these estimates with measured token costs.

**Hard cap:** $20 of prepaid Anthropic API credit with **auto-reload off**, bought before Milestone 5. API credit is separate from any Claude subscription.

**When the cap is reached:** the app catches the API error, shows "AI features are paused," and keeps every SQL view working, because Option B doesn't depend on the LLM.

## 5. Risks and governance

- **If it's wrong:** a wrong deadline means a missed bid. An invented requirement in a draft email embarrasses me with a district I want as a client. Ranking by row counts would favor large, consultant-filed districts over libraries and small schools (`docs/data_quality.md`, Finding 2).
- **Who could be harmed or misled:** me; school and library staff whose names and emails appear on every Form 470; and public website visitors, who might read an AI summary as official USAC information.
- **Data about real people:** contact names, emails, and phone numbers. The data is public domain, but the public site won't republish contact lists, and any outreach must follow CAN-SPAM.
- **The AI must never:**
  - send email or contact anyone without my approval (drafts wait in a review queue)
  - insert, change, or delete data (the chatbot connects as read-only `app_reader`)
  - call the USAC API outside the scheduled sync
  - state a deadline, price, or requirement that isn't in the database
  - show contact details to visitors who aren't signed in

## 6. Scorecard self-assessment (v1)

| # | Factor | Rating | Why |
|---|---|---|---|
| 1 | Real user and workflow | 🟢 Green | I am the user, making a weekly decision documented in my baseline log. |
| 2 | Data access | 🟢 Green | Public-domain Socrata API with an app token, synced every 12 hours by GitHub Actions. |
| 3 | Data understanding | 🟡 Yellow | Seven quality issues are documented, but the data has no coordinates and doesn't show who won a bid. |
| 4 | Freshness and monitoring | 🟡 Yellow | Every run is logged in `sync_runs` and failures email me, but the schedule only started 2026-11-17 and the site doesn't show staleness yet. |
| 5 | Grounding | 🟡 Yellow | The design gets facts from SQL tools, but there's no chatbot yet to prove it. |
| 6 | Bounded autonomy | 🟢 Green | `app_reader` is proven read-only, the Data API is off, and the agent will only draft. |
| 7 | Evaluation | 🔴 Red | No golden questions written yet; "correct" isn't defined. |
| 8 | Measured value and cost | 🔴 Red | Most of my baseline is estimated, and no LLM cost has been measured. |
| 9 | Adoption | 🟡 Yellow | I'm motivated to use it, but my baseline confidence was 2–3 out of 5 and there's no usage yet. |
| 10 | Governance and accountability | 🟡 Yellow | I'm accountable, but real staff contacts are involved and the contact-display rules aren't built yet. |

**Plans for the two weakest factors:**

- **Evaluation (Red → Green):**
  1. By 2026-11-22, write `evals/golden_questions.csv` with at least 15 questions: at least 8 from my baseline and running list, and at least 3 that should be declined (for example "who won this bid?", which the data can't answer).
  2. Run `evals/check_reference.py` as `app_reader` now and again after two more syncs.
  3. In Milestone 5, grade every chatbot answer against the reference SQL.
- **Measured value and cost (Red → Yellow, then Green):**
  1. Treat the E-Rate baseline as an estimate until measured; if needed, time one manual search and add it to the baseline log as a new, dated entry.
  2. From Milestone 4, time every session in the usage log and count bids and contacts.
  3. In Milestone 5, replace the cost estimate with measured cost per question from the API usage page.
