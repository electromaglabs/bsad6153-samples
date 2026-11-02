# BSAD 6153 Project: E-Rate Lead Finder for MSPs

**Student:** Kalynn Samples
**Decision:** A decision I am often having to make is finding potential clients to market my IT and electrical services, I intend to create a hub of various publicly available data sources to find and eventually reach out to potential clients.
**Website:** &lt;your domain, from Week 4&gt;

This repository is one complete AI system, built over eight weeks: a real API, synced on a schedule into a
PostgreSQL database, shown on a public website, with a chatbot and an agent that answer and act from your
own data. You build it with an AI coding agent, and you read and verify everything it writes.

---

## Setting up your computer (Week 1 Setup)

You need a **Windows 10/11 or macOS computer where you can install software**, Git, Python 3.12, and your AI
coding agent (Claude Code, Codex, Antigravity, or Copilot). Let your agent help with the installs, but read
every command before you approve it, and keep auto-approve off.

1. **Clone this repository** into a short folder path that isn't synced by OneDrive or Dropbox, for example
   `C:\dev\bsad6153` on Windows or `~/dev/bsad6153` on macOS.
2. **Create and activate a virtual environment** from the project folder:

   | | Windows (PowerShell) | macOS (Terminal) |
   |---|---|---|
   | Create | `py -3.12 -m venv .venv` | `python3.12 -m venv .venv` |
   | Activate | `.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |

   You'll see `(.venv)` at the start of your prompt when it's active. Activate it every time you open a new terminal.
3. **Install the packages:** `pip install -r requirements.txt`
4. **Create your secrets file:** copy `.env.example` to `.env`, and put a fake value on the `TEST_SECRET=` line.
5. **Check everything:** `python scripts/check_setup.py` should end with `Setup OK`.
6. **Try the website:** `streamlit run app/streamlit_app.py` opens it in your browser. Press Ctrl+C to stop it.

### Code style

Python is formatted and linted with [Ruff](https://docs.astral.sh/ruff/), configured in `pyproject.toml` (120-character
lines). Install it once with `pip install -r requirements-dev.txt`, then run these before each pull request:

```bash
ruff format .
ruff check . --fix
```

`.editorconfig` sets indentation and line endings for every other file type.

### Working with your AI agent

- **You approve every command.** Read it first, and if you don't understand it, ask the agent what it does.
- **Ask for a plan before code:** "Before writing anything, tell me your plan."
- **Never paste a real key into the chat,** and never ask the agent to print your `.env` file.
- **The agent never gets the owner database password or deploy tokens.** That's how agents delete databases.
- **Record what you directed, read, verified, and decided** in each pull request's AI review log.

---

## Project layout

| Folder | What goes there | When |
|---|---|---|
| `ingest/` | Fetch, load, and sync code | Weeks 1&ndash;3 |
| `db/` | `schema.sql`, `roles.sql`, `queries.sql` | Weeks 2&ndash;6 |
| `docs/` | Data dictionary, logs, reports (see `docs/README.md`) | Every week |
| `evals/` | Golden questions and evaluation runs | Weeks 3&ndash;7 |
| `app/` | Your website (Streamlit) | Weeks 4&ndash;6 |
| `examples/` | A reference tool-using chatbot loop | Week 5 |
| `scripts/` | Setup and database checks | Weeks 0&ndash;2 |
| `data/sample/` | A small sample of raw API data (large downloads go in `data/raw/`, which Git ignores) | Week 1 |

## Secrets: where each one lives

| Secret | On your computer | On Render (website) | In GitHub Actions (sync) |
|---|---|---|---|
| `DATABASE_URL` (owner) | `.env` | **never** | Actions secret |
| `APP_DATABASE_URL` (read-only) | `.env` | environment setting | if your checks need it |
| `AGENT_DATABASE_URL` | `.env` | environment setting | no |
| LLM key, `APP_PASSWORD` | `.env` | environment setting | no |
| Data API key | `.env` | no | Actions secret |

`.env.example` lists the names only. If a secret ever leaks, revoke or rotate it first, then tell the instructor.

---

## Deploying on Render (Week 4)

1. Claim your free domain through the GitHub Student Developer Pack.
2. In Render, choose **New &gt; Blueprint**, pick this repository, and enter each secret when asked.
   (`render.yaml` describes the service.) Or create a **Web Service** by hand with:
   - Build command: `pip install -r requirements.txt`
   - Start command: `streamlit run app/streamlit_app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
   - Environment variables: `PYTHON_VERSION=3.12.4`, `APP_DATABASE_URL`, and later your LLM key and `APP_PASSWORD`
3. Under **Settings &gt; Custom Domains**, add your domain, then add the DNS records Render shows you at your
   registrar. Ask your agent to explain each record before you add it. HTTPS turns on automatically.
4. Free services sleep when idle and take about a minute to wake. Say so on your site.

---

## Troubleshooting

- **`pip install` fails with "No such file or directory" on Windows:** the folder path is too long. Move the
  project to a short path such as `C:\dev\bsad6153` and recreate `.venv`.
- **PowerShell says running scripts is disabled when you activate:** use Command Prompt instead and run
  `.venv\Scripts\activate.bat`, or ask the instructor. Don't change system security settings without asking.
- **`python` opens the Microsoft Store or isn't found:** use `py -3.12` on Windows or `python3.12` on macOS.
- **The database check can't connect:** use Supabase's Session pooler string, check the password, and check
  that your Supabase project isn't paused.

---

## Project proposal (Week 1)

**Data source and backup.** The system is built on USAC's E-Rate FCC Form 470 dataset (`jt8s-3q52`), a public,
no-cost Socrata REST API. Every Form 470 is a school, library, or consortium publicly asking vendors to bid on
internet service, network equipment, cabling, or maintenance, with contact details, RFP documents, and the date
bidding closes. New forms are certified daily and old ones are amended or canceled, so there is always something
new to sync. If access breaks, my backup is GeoApify, CMS NPI, NCES Edge School Locations, ProPublica, Overture Maps Places.

**My decision and workflow.** Each week I decide which potential clients my IT and electrical business should
reach out to. Today that means browsing the local business directory (18 minutes in my one timed session),
searching Google, where paid ads bury relevant results (about 26 minutes), and, for schools, hoping districts
contact us when they need E-Rate hardware or sifting through federal E-Rate data by hand, which takes several
hours a week. None of these sources tell me what a prospect actually needs. Form 470 does: it says exactly what a
school is requesting and when bids are due. The system should cut search time and show me requests that match
what my business does well, in time to bid.

**Agent idea (first draft).** Each week, after the sync, an agent finds new or changed Form 470s within about an
hour of Alva, Oklahoma (including southern Kansas), ranks them by how well the requested services fit my
business, and **drafts** a short, tailored outreach email for each one, with the bid deadline and RFP links. It
never sends anything: every draft waits in a review queue until I approve it.

**Risks.**
- *Rate limits:* low today with an app token, but Socrata can change limits; the fetch backs off on 429s.
- *Token:* an app token could be revoked or leak; it lives only in `.env` and GitHub secrets.
- *Data volume:* rows multiply per RFP attachment (1,457 rows were only 129 applications); expanding states or
  years grows quickly.
- *Terms and ethics:* the data is public domain, but it contains real staff names and emails, so outreach must follow
  commercial-email rules (CAN-SPAM) and the site should not republish contact lists.
- *Timing:* a missed `allowable_contract_date` means a missed bid, so the sync schedule has to be reliable.

## How to run this project

### Fetch the data (Week 1)

1. Activate the virtual environment: `source .venv/bin/activate` (macOS) or `.venv\Scripts\Activate.ps1` (Windows).
2. Install packages if you haven't: `pip install -r requirements.txt`
3. Optional but recommended: get a free Socrata **app token** from opendata.usac.org (developer settings) and put it in `.env`
   as `SOCRATA_APP_TOKEN=...`. Without it the script still runs, with lower rate limits.
4. Run the fetch:

   ```bash
   python ingest/fetch.py                                  # Oklahoma + Kansas, funding year 2027
   python ingest/fetch.py --states OK KS --years 2026 2027 # other states or years
   python ingest/fetch.py --page-size 200                  # smaller pages (more requests)
   ```

5. Output:
   - Raw API responses: `data/raw/<run time>/service_requests/page_NNN.json` and `.../applicants/page_NNN.json` (ignored by Git)
   - Run summary (counts, missing fields, HTTP retries): `data/raw/<run time>/summary.json`
   - Small samples for Git: `data/sample/service_requests_sample.json`, `data/sample/applicants_sample.json`

The script exits with code 0 when it got at least 500 rows and no pages failed, and 1 otherwise.
See `docs/data_dictionary.md` for what the data means.

## Credits

- **Data:** E-Rate FCC Form 470 Tool Data, Universal Service Administrative Company (USAC),
  https://opendata.usac.org (dataset `jt8s-3q52`). Published as public domain; attribution to USAC.
- **API:** Socrata Open Data API (SODA 2.1), https://dev.socrata.com
- **Course template:** BSAD 6153 project repository template.
